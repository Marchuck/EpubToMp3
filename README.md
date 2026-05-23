# EpubToMp3
moves you books you don't have time to sit and read to audiobooks! 


# Modus Operandi

1. grab your epub and move to chapter_X.txt (epub -> txt script available in this repo)

2.  donwload piper, and download the model you need, eg male polish voice:

```bash
wget https://huggingface.co/WitoldG/polish_piper_models/resolve/main/pl_PL-jarvis_wg_glos-medium.onnx
wget https://huggingface.co/WitoldG/polish_piper_models/resolve/main/pl_PL-jarvis_wg_glos-medium.onnx.json
```

move txt to wav

```bash
source /Users/user/path_to_your_project/piper/venv/bin/activate
piper --model pl_PL-jarvis_wg_glos-medium.onnx --output_file chapter_X.wav < chapter_X.txt
```

3. WAV -> MP3 (optional)

```bash
ffmpeg -i chapter_X.wav -codec:a libmp3lame -qscale:a 4 chapter_X.mp3
```
