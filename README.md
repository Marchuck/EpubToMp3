# EpubToAudiobook
moves you books you don't have time to sit and read to audiobooks! 


# Modus Operandi

1. Grab your epub and split to chapters/subchapters

  ```shell
  source venv/bin/activate
  python3 epub_splitter.py your_ebook.epub -o target_directory/txt/
  ``` 

2. Download piper, and get the model you wish (e.g. from [here](https://huggingface.co/WitoldG/polish_piper_models), I used polish male voice:

```bash
wget https://huggingface.co/WitoldG/polish_piper_models/resolve/main/pl_PL-jarvis_wg_glos-medium.onnx
wget https://huggingface.co/WitoldG/polish_piper_models/resolve/main/pl_PL-jarvis_wg_glos-medium.onnx.json
```

3. Create audiobook from txt using splitted chapters from previous step:

```bash
source piper/venv/bin/activate
./build_audiobook.sh target_directory/
```
