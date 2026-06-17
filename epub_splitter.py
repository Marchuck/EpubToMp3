#!/usr/bin/env python3
"""Split an EPUB file into individual chapter/subchapter .txt files."""

import argparse
import glob
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag
import ebooklib
from ebooklib import epub


# ---------------------------------------------------------------------------
# Subchapter heading detection
# ---------------------------------------------------------------------------

# Matches headings that look like a subchapter number, e.g.:
#   "1"  "12"  "1."  "Rozdział 3"  "Rozdzial 3"  "Podrozdział 4"  "Część 2"
#   "Chapter 5"  "CHAPTER 5"
_SUBCHAPTER_RE = re.compile(
    r"""^
    (?:
        (?:rozdzia[lł]|podrozdzia[lł]|cz[eę][sś][cć]|chapter|part)\s*\.?\s*
    )?
    (\d{1,3})   # the actual number we care about
    \.?$        # optional trailing dot
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _heading_subchapter_number(text: str) -> Optional[int]:
    """Return the subchapter number if *text* looks like a subchapter heading, else None."""
    t = text.strip()
    m = _SUBCHAPTER_RE.match(t)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """A piece of text that will become one output file."""
    chapter_num: int
    sub_num: Optional[int]   # None → whole chapter (no subchapters detected)
    text: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_epub(directory: str) -> Optional[str]:
    epubs = glob.glob(os.path.join(directory, "*.epub"))
    return epubs[0] if epubs else None


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", name)


def extract_title(soup: BeautifulSoup, fallback: str) -> str:
    for tag in ("h1", "h2", "h3", "title"):
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return fallback


def extract_text(soup: BeautifulSoup) -> str:
    body = soup.find("body")
    if body is None:
        return ""
    return body.get_text(separator="\n").strip()


# ---------------------------------------------------------------------------
# Core: split HTML item into segments by detected subchapter headings
# ---------------------------------------------------------------------------

def split_into_segments(soup: BeautifulSoup, chapter_num: int) -> list[Segment]:
    """
    Walk the body's direct children looking for subchapter heading nodes.
    A heading node is any <h1>–<h4> OR a <p>/<div> whose *entire* text
    matches the subchapter pattern.

    Returns a list of Segment objects.  If no subchapter headings are found,
    returns a single Segment with sub_num=None.
    """
    body = soup.find("body")
    if body is None:
        return []

    # Collect (node, is_subchapter_heading, subchapter_number) for all
    # block-level direct children (and shallowly nested ones).
    blocks: list[tuple[Tag, Optional[int]]] = []
    for node in body.descendants:
        if not isinstance(node, Tag):
            continue
        # Only consider block-level tags that are direct/near-direct children
        if node.name not in ("h1", "h2", "h3", "h4", "p", "div"):
            continue
        # Skip nodes that contain other block children (avoid double-counting)
        if node.find(["h1", "h2", "h3", "h4", "p", "div"]):
            continue
        raw = node.get_text(strip=True)
        if not raw:
            continue
        sub_num = _heading_subchapter_number(raw)
        blocks.append((node, sub_num))

    # Determine whether this item has any subchapter headings at all
    heading_positions = [i for i, (_, sn) in enumerate(blocks) if sn is not None]

    if not heading_positions:
        # No subchapters — return whole text as one segment
        text = body.get_text(separator="\n").strip()
        if len(text) < 50:
            return []
        return [Segment(chapter_num=chapter_num, sub_num=None, text=text)]

    # Build segments: text between consecutive heading positions
    segments: list[Segment] = []

    # Text before the first heading (preamble) — attach to chapter-level segment
    # only if it has meaningful content; otherwise discard.
    preamble_blocks = blocks[: heading_positions[0]]
    preamble_text = "\n".join(
        node.get_text(separator="\n") for node, _ in preamble_blocks
    ).strip()

    # We'll prepend preamble to the first subchapter if it's short,
    # or make it sub 0 if it's substantial (>= 50 chars).
    carry_preamble = preamble_text if len(preamble_text) >= 50 else ""
    prepend_to_first = preamble_text if 0 < len(preamble_text) < 50 else ""

    for idx, pos in enumerate(heading_positions):
        _, sub_num = blocks[pos]
        # Gather text nodes from this heading to the next heading (exclusive)
        end = heading_positions[idx + 1] if idx + 1 < len(heading_positions) else len(blocks)
        chunk_blocks = blocks[pos:end]
        chunk_text = "\n".join(
            node.get_text(separator="\n") for node, _ in chunk_blocks
        ).strip()

        if idx == 0 and prepend_to_first:
            chunk_text = prepend_to_first + "\n" + chunk_text

        if len(chunk_text) < 50:
            continue

        segments.append(Segment(chapter_num=chapter_num, sub_num=sub_num, text=chunk_text))

    # If preamble was substantial, prepend as sub_num derived from context
    # Actually: insert it as the first segment with sub_num = segments[0].sub_num - 1
    # but only if we can do so cleanly (i.e. first sub is > 1).  Otherwise discard.
    if carry_preamble:
        first_sub = segments[0].sub_num if segments else 1
        if first_sub is not None and first_sub > 1:
            segments.insert(0, Segment(chapter_num=chapter_num, sub_num=first_sub - 1, text=carry_preamble))
        # else: discard preamble — can't assign a sensible number

    return segments


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Split an EPUB file into individual chapter/subchapter .txt files."
    )
    parser.add_argument("epub", nargs="?", default=None, help="Path to the EPUB file (auto-detected if omitted)")
    parser.add_argument("-o", "--output", default="output", help="Output directory (default: output)")
    args = parser.parse_args()

    if args.epub:
        epub_path = os.path.abspath(args.epub)
        if not os.path.isfile(epub_path):
            print(f"File not found: {epub_path}")
            sys.exit(1)
    else:
        epub_path = find_epub(script_dir)
        if epub_path is None:
            print("No .epub file found in the current directory.")
            print("Usage: python epub_splitter.py [path/to/book.epub] [-o OUTPUT_DIR]")
            sys.exit(1)

    print(f"Reading: {epub_path}")
    book = epub.read_epub(epub_path)

    output_dir = os.path.abspath(args.output)
    os.makedirs(output_dir, exist_ok=True)

    # --- Pass 1: collect raw items, skip truly empty ones, merge "empty chapter"
    #             title pages with the next real content item. ---

    raw_items: list[tuple[str, BeautifulSoup, bool]] = []  # (item_id, soup, has_content)

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html_content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_content, "html.parser")
        text = extract_text(soup)
        if len(text) < 50:
            raw_items.append((item.get_id(), soup, False))
        else:
            raw_items.append((item.get_id(), soup, True))

    # Merge: attach each leading empty item's text to the next content item
    merged: list[BeautifulSoup] = []
    pending_prefix: list[BeautifulSoup] = []

    for _item_id, soup, has_content in raw_items:
        if not has_content:
            pending_prefix.append(soup)
        else:
            if pending_prefix:
                # Combine: prepend pending bodies into this soup's body
                body = soup.find("body")
                if body:
                    for prefix_soup in pending_prefix:
                        prefix_body = prefix_soup.find("body")
                        if prefix_body:
                            for child in list(prefix_body.children):
                                body.insert(0, child)
                pending_prefix.clear()
            merged.append(soup)

    # Any trailing empty items at end → discard (they're back matter like nav)

    # --- Pass 2: split each merged item into segments ---

    all_segments: list[Segment] = []
    for chapter_num, soup in enumerate(merged, start=1):
        segs = split_into_segments(soup, chapter_num)
        all_segments.extend(segs)

    # --- Pass 3: write files ---

    if not all_segments:
        print("No chapters with content found.")
        sys.exit(0)

    files_written = 0
    for seg in all_segments:
        if seg.sub_num is None:
            filename = f"ch_{seg.chapter_num:03d}.txt"
        else:
            filename = f"ch_{seg.chapter_num:03d}_{seg.sub_num:02d}.txt"

        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(seg.text)

        print(f"  {filename} ({len(seg.text)} chars)")
        files_written += 1

    print(f"Done — {files_written} files written to {output_dir}")


if __name__ == "__main__":
    main()
