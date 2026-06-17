#!/usr/bin/env bash
# build_audiobook.sh <ebook_dir>
# Zakłada strukturę:
#   <parent>/piper/venv/bin/activate
#   <parent>/piper/pl_PL-jarvis_wg_glos-medium.onnx
#   <ebook_dir>/txt/   — pliki ch_NNN.txt lub ch_NNN_NN.txt
#   <ebook_dir>/mp3/        — MP3 per podrozdział (z Pipera)
#   <ebook_dir>/mp3_merged/ — scalone rozdziały z markerami

set -euo pipefail

# ── Argumenty ────────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Użycie: $0 <ebook_dir>" >&2
    exit 1
fi

EBOOK_DIR="$(cd "${1%/}" && pwd)"
TXT_DIR="$EBOOK_DIR/txt"
MP3_DIR="$EBOOK_DIR/mp3"
MERGED_DIR="$EBOOK_DIR/mp3_merged"
PIPER_DIR="$(dirname "$EBOOK_DIR")/piper"
MODEL="$PIPER_DIR/pl_PL-jarvis_wg_glos-medium.onnx"
MAX_SECONDS=3600  # 1 godzina

if [[ ! -d "$TXT_DIR" ]]; then
    echo "Błąd: katalog $TXT_DIR nie istnieje" >&2
    exit 1
fi
mkdir -p "$MP3_DIR"
mkdir -p "$MERGED_DIR"

# ── Aktywacja venv ────────────────────────────────────────────────────────────
# shellcheck source=/dev/null
source "$PIPER_DIR/venv/bin/activate"

# ── Sprawdź mutagen, zaproponuj instalację jeśli brak ────────────────────────
if ! python3 -c "import mutagen" 2>/dev/null; then
    echo ""
    echo "⚠️  mutagen nie jest zainstalowany w venv."
    echo "   Bez niego nie można dodać markerów rozdziałów do MP3."
    read -r -p "   Zainstalować teraz? (pip install mutagen) [T/n]: " ans
    ans="${ans:-T}"
    if [[ "$ans" =~ ^[Tt]$ ]]; then
        pip install --quiet mutagen
        if ! python3 -c "import mutagen" 2>/dev/null; then
            echo "❌ Instalacja nie powiodła się. Przerywam." >&2
            exit 1
        fi
        echo "✅ mutagen zainstalowany."
    else
        echo "❌ mutagen wymagany — przerywam." >&2
        exit 1
    fi
fi

# ── 1. TXT → WAV → MP3 (per podrozdział / rozdział) ─────────────────────────
read -r -p "=== Faza 1: generować MP3 z TXT przez Piper? [T/n]: " do_tts
do_tts="${do_tts:-T}"
if [[ "$do_tts" =~ ^[Tt]$ ]]; then
    echo "=== Faza 1: generowanie MP3 z TXT ==="
    for txt_file in "$TXT_DIR"/ch_*.txt; do
        [[ -f "$txt_file" ]] || continue
        base=$(basename "$txt_file" .txt)
        wav_file="$MP3_DIR/${base}.wav"
        mp3_file="$MP3_DIR/${base}.mp3"

        echo "  Piper: $base.txt → $base.mp3"
        piper \
            --model "$MODEL" \
            --output_file "$wav_file" \
            < "$txt_file"

        ffmpeg -y -loglevel error \
            -i "$wav_file" \
            -codec:a libmp3lame -qscale:a 4 \
            "$mp3_file"

        rm -f "$wav_file"
    done
else
    echo "=== Faza 1: pomijam generowanie MP3 ==="
fi

# ── 2. Grupowanie plików MP3 według rozdziałów ────────────────────────────────
echo "=== Faza 2: grupowanie i scalanie ==="

python3 - "$MP3_DIR" "$MERGED_DIR" "$MAX_SECONDS" << 'PYEOF'
import sys
import os
import re
import subprocess
from collections import defaultdict
from mutagen.id3 import ID3, CHAP, CTOC, TIT2, CTOCFlags, ID3NoHeaderError

mp3_dir    = sys.argv[1]
merged_dir = sys.argv[2]
max_sec    = int(sys.argv[3])

def get_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())

def chapter_sort_key(filename):
    m = re.match(r'ch_(\d+)(?:_(\d+))?\.mp3$', filename)
    if not m:
        return (9999, 9999)
    ch  = int(m.group(1))
    sub = int(m.group(2)) if m.group(2) else 0
    return (ch, sub)

def friendly_name(filename):
    m = re.match(r'ch_(\d+)(?:_(\d+))?\.mp3$', filename)
    if not m:
        return filename
    ch  = int(m.group(1))
    sub = int(m.group(2)) if m.group(2) else None
    if sub is None:
        return f"Rozdział {ch}"
    return f"Rozdział {ch} Podrozdział {sub}"

def write_chapters(mp3_path, chapters):
    """Wpisuje ID3 CHAP + CTOC. Rzuca wyjątek przy błędzie — caller decyduje co robić."""
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    tags.delall("CHAP")
    tags.delall("CTOC")

    elem_ids = []
    for i, ch in enumerate(chapters):
        elem_id = f"ch{i}"
        elem_ids.append(elem_id)
        tags.add(CHAP(
            element_id=elem_id,
            start_time=ch["start_ms"],
            end_time=ch["end_ms"],
            start_offset=0xFFFFFFFF,
            end_offset=0xFFFFFFFF,
            sub_frames=[TIT2(encoding=3, text=ch["title"])]
        ))

    tags.add(CTOC(
        element_id="toc",
        flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
        child_element_ids=elem_ids,
        sub_frames=[TIT2(encoding=3, text="Table of Contents")]
    ))

    tags.save(mp3_path, v2_version=3)
    print(f"    Zapisano {len(chapters)} markerów do {os.path.basename(mp3_path)}")

# Zbierz wszystkie mp3 składowe (tylko ch_NNN.mp3 i ch_NNN_NN.mp3, nie _partN)
all_mp3 = sorted(
    [f for f in os.listdir(mp3_dir) if re.match(r'ch_\d+(_\d+)?\.mp3$', f)],
    key=chapter_sort_key
)

groups = defaultdict(list)
for f in all_mp3:
    m = re.match(r'ch_(\d+)', f)
    if m:
        groups[int(m.group(1))].append(f)

for ch_num in sorted(groups.keys()):
    files = groups[ch_num]

    durations = []
    for f in files:
        d = get_duration(os.path.join(mp3_dir, f))
        durations.append(d)
        print(f"  {f}: {d:.1f}s")

    # Podział na części <= max_sec (cięcie między plikami)
    parts = []
    current_part = []
    current_dur  = 0.0
    for f, d in zip(files, durations):
        if current_part and current_dur + d > max_sec:
            parts.append(current_part)
            current_part = [f]
            current_dur  = d
        else:
            current_part.append(f)
            current_dur += d
    if current_part:
        parts.append(current_part)

    dur_map = dict(zip(files, durations))

    for part_idx, part_files in enumerate(parts):
        if len(parts) == 1:
            out_name = f"ch_{ch_num:03d}.mp3"
        else:
            out_name = f"ch_{ch_num:03d}_part{part_idx+1}.mp3"

        out_path = os.path.join(merged_dir, out_name)
        print(f"\n  → Tworzę: {out_name}  ({len(part_files)} plików)")

        # Scal przez ffmpeg concat
        list_path = os.path.join(merged_dir, "_concat_list.txt")
        with open(list_path, "w") as lf:
            for f in part_files:
                lf.write(f"file '{os.path.join(mp3_dir, f)}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0",
             "-i", list_path,
             "-codec:a", "copy",
             out_path],
            check=True
        )
        os.remove(list_path)

        # Markery — tylko gdy >1 plik składowy
        if len(part_files) > 1:
            chapters = []
            cursor_ms = 0
            for f in part_files:
                d_ms = int(dur_map[f] * 1000)
                chapters.append({
                    "title":    friendly_name(f),
                    "start_ms": cursor_ms,
                    "end_ms":   cursor_ms + d_ms
                })
                cursor_ms += d_ms

            try:
                write_chapters(out_path, chapters)
            except Exception as e:
                # Znaczniki się nie udały — cofnij: usuń scalone, zachowaj składowe
                print(f"    ❌ Błąd zapisu markerów: {e}")
                print(f"    ↩️  Usuwam {out_name}. Pliki składowe pozostają w mp3/.")
                os.remove(out_path)
                continue  # nie usuwaj składowych

        else:
            print(f"    Jeden plik — bez markerów")



print("\n=== Gotowe ===")
PYEOF

echo "Wszystko gotowe."
echo "  MP3 per podrozdział : $MP3_DIR"
echo "  Scalone z markerami : $MERGED_DIR"
