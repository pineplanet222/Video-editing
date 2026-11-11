#!/usr/bin/env bash
# One-shot installer for the video-editing toolchain:
#   1. FFmpeg        - cut, join and convert any video file
#   2. yt-dlp        - download videos from YouTube, Instagram and more
#   3. whisper.cpp   - speech to text, locally (CPU build + base.en model)
#   4. Remotion      - make videos programmatically with React  (./remotion-project)
#   5. HyperFrames   - motion graphics and 3D as HTML             (./hyperframes-project)
#
# Works on macOS (Homebrew) and Debian/Ubuntu Linux. Safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

WHISPER_MODEL="${WHISPER_MODEL:-base.en}"
HYPERFRAMES_VERSION="${HYPERFRAMES_VERSION:-0.9.31}"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARN: %s\033[0m\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
if [ "$(id -u)" -ne 0 ] && have sudo; then SUDO="sudo"; fi

# ---------------------------------------------------------------- prerequisites
log "Checking prerequisites (git, node, python3, cmake, C++ compiler)"
if have brew; then
  for pkg in git node python cmake; do have "${pkg/python/python3}" || brew install "$pkg"; done
elif have apt-get; then
  need=()
  have git    || need+=(git)
  have cmake  || need+=(cmake)
  have g++    || need+=(build-essential)
  have python3 || need+=(python3 python3-pip)
  have node   || need+=(nodejs npm)
  if [ ${#need[@]} -gt 0 ]; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq "${need[@]}"
  fi
fi
for bin in git node npm python3 cmake; do
  have "$bin" || { echo "Missing required tool: $bin" >&2; exit 1; }
done

# ---------------------------------------------------------------- 1. FFmpeg
log "1/5 FFmpeg"
if ! have ffmpeg; then
  if   have brew;    then brew install ffmpeg
  elif have apt-get; then $SUDO apt-get install -y -qq ffmpeg
  else warn "Install FFmpeg manually: https://ffmpeg.org/download.html"; fi
fi
ffmpeg -version | head -1

# ---------------------------------------------------------------- 2. yt-dlp
log "2/5 yt-dlp"
if have brew; then
  have yt-dlp || brew install yt-dlp
elif have pipx; then
  pipx install --force yt-dlp >/dev/null
else
  python3 -m pip install --quiet --upgrade yt-dlp 2>/dev/null \
    || python3 -m pip install --quiet --upgrade --break-system-packages yt-dlp
fi
yt-dlp --version

# ---------------------------------------------------------------- 3. whisper.cpp
log "3/5 whisper.cpp (ggml-org/whisper.cpp)"
mkdir -p tools
if [ ! -d tools/whisper.cpp/.git ]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git tools/whisper.cpp
fi
cmake -S tools/whisper.cpp -B tools/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build tools/whisper.cpp/build -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu)" --config Release >/dev/null
ls tools/whisper.cpp/build/bin/whisper-cli

MODEL_FILE="tools/whisper.cpp/models/ggml-${WHISPER_MODEL}.bin"
if [ ! -s "$MODEL_FILE" ]; then
  if ! bash tools/whisper.cpp/models/download-ggml-model.sh "$WHISPER_MODEL" >/dev/null; then
    rm -f "$MODEL_FILE"
    warn "Could not download whisper model '$WHISPER_MODEL' (network blocked?)."
    warn "Later, run: bash tools/whisper.cpp/models/download-ggml-model.sh $WHISPER_MODEL"
  fi
fi
[ -s "$MODEL_FILE" ] && echo "model: $MODEL_FILE" || true

# ---------------------------------------------------------------- 4. Remotion
log "4/5 Remotion (./remotion-project)"
( cd remotion-project && npm install --no-audit --no-fund --loglevel=error )
( cd remotion-project && npx remotion versions )

# ---------------------------------------------------------------- 5. HyperFrames
log "5/5 HyperFrames (./hyperframes-project)"
( cd hyperframes-project && npm install --no-audit --no-fund --loglevel=error )
( cd hyperframes-project && npx --yes "hyperframes@${HYPERFRAMES_VERSION}" --version )

log "All tools installed. Run ./test.sh to exercise each one."
