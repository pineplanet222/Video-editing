# Video-editing toolchain

Everything needed to let an AI coding agent act as a video editor, installed by one script:

| # | Tool | What it does | Where |
|---|------|--------------|-------|
| 1 | [Remotion](https://github.com/remotion-dev/remotion) | Make videos programmatically with React | `remotion-project/` |
| 2 | [HyperFrames](https://github.com/heygen-com/hyperframes) | Motion graphics and 3D as HTML | `hyperframes-project/` |
| 3 | [FFmpeg](https://github.com/FFmpeg/FFmpeg) | Cut, join and convert any video file | system install |
| 4 | [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Speech to text, on your own computer | `tools/whisper.cpp/` (built from source) |
| 5 | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Download videos from YouTube, Instagram and more | system install |

## Install

```bash
./setup.sh   # macOS (Homebrew) or Debian/Ubuntu; safe to re-run
./test.sh    # exercises every tool, writes sample outputs to ./out
```

`setup.sh` installs FFmpeg and yt-dlp, clones and compiles whisper.cpp with the
`base.en` model, and installs the dependencies of both the Remotion and HyperFrames
sample projects. Set `WHISPER_MODEL=small.en` (or any other ggml model name) before
running it to pick a different model.

## Everyday commands

```bash
# FFmpeg: trim the first 10 seconds and convert to MP4
ffmpeg -i input.mov -t 10 -c:v libx264 -c:a aac output.mp4

# yt-dlp: download a clip
yt-dlp "https://www.youtube.com/watch?v=..."

# whisper.cpp: transcribe to SRT (audio must be 16 kHz mono WAV)
ffmpeg -i input.mp4 -ar 16000 -ac 1 -c:a pcm_s16le audio.wav
tools/whisper.cpp/build/bin/whisper-cli -m tools/whisper.cpp/models/ggml-base.en.bin -f audio.wav -osrt

# Remotion
cd remotion-project && npm run dev            # studio in the browser
cd remotion-project && npx remotion render MyComp out/video.mp4

# HyperFrames
cd hyperframes-project && npm run dev         # live preview
cd hyperframes-project && npm run check       # lint the composition
cd hyperframes-project && npm run render      # render to ./renders/*.mp4
```

`tools/`, `out/`, `renders/` and `node_modules/` are git-ignored; re-run `setup.sh`
on a fresh clone to recreate them.
