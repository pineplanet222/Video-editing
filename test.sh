#!/usr/bin/env bash
# Exercises every tool installed by setup.sh. Outputs go to ./out (git-ignored).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
OUT="$ROOT/out"; mkdir -p "$OUT"
WHISPER_MODEL="${WHISPER_MODEL:-base.en}"
pass() { printf '\033[1;32mPASS\033[0m %s\n' "$*"; }
log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# Remotion downloads its own Chrome Headless Shell on first render. If a Chromium
# binary is already on the machine you can point at it with REMOTION_BROWSER.
BROWSER_FLAG=()
if [ -n "${REMOTION_BROWSER:-}" ]; then BROWSER_FLAG=(--browser-executable "$REMOTION_BROWSER")
elif [ -x /opt/pw-browsers/chromium ]; then BROWSER_FLAG=(--browser-executable /opt/pw-browsers/chromium); fi

log "FFmpeg: generate a 2s test clip with a tone, then re-encode it"
ffmpeg -y -v error -f lavfi -i "testsrc=size=640x360:rate=30" -f lavfi -i "sine=frequency=440" \
  -t 2 -c:v libx264 -pix_fmt yuv420p -c:a aac "$OUT/ffmpeg-test.mp4"
ffmpeg -y -v error -i "$OUT/ffmpeg-test.mp4" -vf scale=320:-2 "$OUT/ffmpeg-test-small.mp4"
ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 "$OUT/ffmpeg-test-small.mp4"
pass "FFmpeg"

log "yt-dlp: version and extractor list"
yt-dlp --version
yt-dlp --list-extractors | grep -ciE '^(youtube|instagram)' | xargs -I{} echo "{} YouTube/Instagram extractors available"
pass "yt-dlp"

log "whisper.cpp: transcribe the bundled JFK sample"
MODEL="tools/whisper.cpp/models/ggml-${WHISPER_MODEL}.bin"
if [ -s "$MODEL" ]; then
  tools/whisper.cpp/build/bin/whisper-cli -m "$MODEL" -f tools/whisper.cpp/samples/jfk.wav -np -nt 2>/dev/null | tee "$OUT/whisper-jfk.txt"
  grep -qi "ask not what your country" "$OUT/whisper-jfk.txt"
  pass "whisper.cpp"
else
  echo "SKIP whisper.cpp: model $MODEL missing (run setup.sh with network access)"
fi

log "Remotion: render the sample composition"
( cd remotion-project && npx remotion render MyComp "$OUT/remotion-test.mp4" "${BROWSER_FLAG[@]}" --log=error )
ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 "$OUT/remotion-test.mp4"
pass "Remotion"

log "HyperFrames: check and render the sample composition"
( cd hyperframes-project && npm run --silent check 2>&1 | tail -3 && npm run --silent render 2>&1 | grep -E "renders/.*\.mp4" )
pass "HyperFrames"

log "All tools working."
