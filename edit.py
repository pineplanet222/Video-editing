#!/usr/bin/env python3
"""
AI Video Editor — edit.py

Usage:
  python3 edit.py <input_video> [options]

Options:
  --pause-threshold SECS   Silence threshold in seconds (default: 0.1)
  --silence-db DB          Volume level (dBFS) considered silence (default: -40)
  --music PATH             Background music file (optional)
  --music-volume FLOAT     Background music volume 0–1 (default: 0.15)
  --brand-color COLOR      Primary brand color hex (default: #FF4444)
  --font-color COLOR       Caption font color hex (default: #FFFFFF)
  --approve                Skip storyboard approval and render immediately
  --output-dir DIR         Where to write output files (default: ./out)

Workflow:
  1. Transcribe audio with whisper.cpp → timed captions
  2. Detect and cut silences > pause_threshold seconds
  3. Build a storyboard JSON with Keep / Change / Drop for each segment
  4. Print storyboard and wait for approval (unless --approve)
  5. Render final MP4 with captions and optional background music
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd: list, check: bool = True, capture: bool = False, **kw):
    """Run a subprocess, printing the command for transparency."""
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    if capture:
        return subprocess.run(cmd, check=check, capture_output=True, text=True, **kw)
    return subprocess.run(cmd, check=check, **kw)


def ffmpeg(*args, **kw):
    return run(["ffmpeg", "-y", "-v", "error", *args], **kw)


def probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True
    )
    return float(r.stdout.strip())


# ---------------------------------------------------------------------------
# Step 1 — Transcription with whisper.cpp
# ---------------------------------------------------------------------------

def transcribe(video: str, model_path: str, wav_tmp: str) -> list[dict]:
    """
    Returns a list of dicts: {start, end, text}
    """
    print("\n[1/4] Transcribing audio with whisper.cpp …")
    ffmpeg("-i", video, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_tmp)

    whisper_bin = Path(__file__).parent / "tools/whisper.cpp/build/bin/whisper-cli"
    r = run([str(whisper_bin), "-m", model_path, "-f", wav_tmp,
             "--output-json", "--no-prints", "-nt"],
            capture=True, check=False)

    # whisper-cli writes <wav_tmp>.json
    json_path = wav_tmp + ".json"
    if os.path.exists(json_path):
        with open(json_path) as f:
            data = json.load(f)
        segments = []
        for seg in data.get("transcription", []):
            ts = seg.get("timestamps", {})
            start_ms = ts.get("from", "0:00:00.000")
            end_ms   = ts.get("to",   "0:00:00.000")
            segments.append({
                "start": _ts_to_sec(start_ms),
                "end":   _ts_to_sec(end_ms),
                "text":  seg.get("text", "").strip(),
            })
        print(f"  → {len(segments)} transcript segments")
        return segments

    # Fallback: parse stdout timestamp lines
    lines = r.stdout or ""
    segments = []
    for m in re.finditer(
        r"\[(\d+:\d+:\d+\.\d+) --> (\d+:\d+:\d+\.\d+)\]\s+(.*)", lines
    ):
        segments.append({
            "start": _ts_to_sec(m.group(1)),
            "end":   _ts_to_sec(m.group(2)),
            "text":  m.group(3).strip(),
        })
    print(f"  → {len(segments)} transcript segments (fallback parser)")
    return segments


def _ts_to_sec(ts: str) -> float:
    """Convert 'H:MM:SS.mmm', 'H:MM:SS,mmm', or 'MM:SS.mmm' to seconds."""
    ts = ts.replace(",", ".")   # whisper uses comma as decimal separator
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


# ---------------------------------------------------------------------------
# Step 2 — Silence / pause detection
# ---------------------------------------------------------------------------

def detect_pauses(video: str, threshold_sec: float, silence_db: float) -> list[dict]:
    """
    Uses ffmpeg silencedetect filter.
    Returns list of {start, end, duration} for detected silences > threshold.
    """
    print(f"\n[2/4] Detecting pauses > {threshold_sec}s …")
    r = subprocess.run(
        ["ffmpeg", "-i", video, "-af",
         f"silencedetect=noise={silence_db}dB:d={threshold_sec}",
         "-f", "null", "-"],
        capture_output=True, text=True
    )
    output = r.stderr
    pauses = []
    starts = re.findall(r"silence_start: ([\d.]+)", output)
    ends   = re.findall(r"silence_end: ([\d.]+)", output)
    durs   = re.findall(r"silence_duration: ([\d.]+)", output)

    for s, e, d in zip(starts, ends, durs):
        pauses.append({"start": float(s), "end": float(e), "duration": float(d)})

    print(f"  → {len(pauses)} pauses found")
    return pauses


def build_keep_segments(total_duration: float, pauses: list[dict]) -> list[tuple]:
    """
    Returns list of (start, end) tuples for non-silent portions.
    """
    if not pauses:
        return [(0.0, total_duration)]

    segments = []
    cursor = 0.0
    for p in pauses:
        if p["start"] > cursor + 0.001:
            segments.append((cursor, p["start"]))
        cursor = p["end"]
    if cursor < total_duration - 0.001:
        segments.append((cursor, total_duration))
    return segments


def cut_pauses(video: str, segments: list[tuple], output: str, pauses: list[dict]):
    """Cut pauses using ffmpeg concat demuxer."""
    print(f"\n  Cutting {len(pauses)} pauses → {len(segments)} segments …")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        list_path = f.name
        for start, end in segments:
            duration = end - start
            f.write(f"file '{os.path.abspath(video)}'\n")
            f.write(f"inpoint {start:.6f}\n")
            f.write(f"outpoint {end:.6f}\n")

    ffmpeg("-f", "concat", "-safe", "0", "-i", list_path,
           "-c", "copy", output)
    os.unlink(list_path)
    print(f"  → Saved to {output}")


# ---------------------------------------------------------------------------
# Step 3 — Storyboard
# ---------------------------------------------------------------------------

def build_storyboard(segments: list[tuple], transcript: list[dict],
                     brand_color: str, font_color: str) -> list[dict]:
    """
    Map transcript segments onto cut video segments.
    Each storyboard entry has: index, start, end, duration, text,
    captions, suggestion (Keep/Change/Drop), notes.
    """
    print("\n[3/4] Building storyboard …")
    board = []

    for i, (seg_start, seg_end) in enumerate(segments):
        seg_mid = (seg_start + seg_end) / 2
        # Find transcript lines that overlap this segment
        texts = [t["text"] for t in transcript
                 if t["start"] <= seg_end and t["end"] >= seg_start]
        caption = " ".join(texts).strip() or "[no speech]"

        duration = seg_end - seg_start
        # Heuristic suggestion
        if duration < 0.5:
            suggestion = "Drop"
            notes = "Very short clip — likely a cut artefact."
        elif len(caption) < 10 or caption == "[no speech]":
            suggestion = "Change"
            notes = "Little or no speech — add B-roll or music."
        elif duration > 15:
            suggestion = "Change"
            notes = "Long segment — consider splitting or adding a graphic."
        else:
            suggestion = "Keep"
            notes = "Good pacing and clear speech."

        board.append({
            "index":      i + 1,
            "start":      round(seg_start, 3),
            "end":        round(seg_end, 3),
            "duration":   round(duration, 3),
            "caption":    caption,
            "suggestion": suggestion,
            "notes":      notes,
            "brand_color": brand_color,
            "font_color":  font_color,
        })

    keep  = sum(1 for s in board if s["suggestion"] == "Keep")
    change = sum(1 for s in board if s["suggestion"] == "Change")
    drop  = sum(1 for s in board if s["suggestion"] == "Drop")
    print(f"  → {len(board)} segments: {keep} Keep / {change} Change / {drop} Drop")
    return board


def print_storyboard(board: list[dict]):
    print("\n" + "=" * 72)
    print("  STORYBOARD — review each segment and edit storyboard.json to")
    print("  change Keep / Change / Drop, then run with --approve to render.")
    print("=" * 72)
    for s in board:
        icon = {"Keep": "✅", "Change": "⚡", "Drop": "🗑 "}.get(s["suggestion"], "  ")
        ts = f"{s['start']:>7.2f}s – {s['end']:>7.2f}s ({s['duration']:.2f}s)"
        print(f"\n  [{s['index']:>3}] {icon} {s['suggestion']:<6}  {ts}")
        print(f"       Caption : {s['caption'][:72]}")
        print(f"       Notes   : {s['notes']}")
    print("\n" + "=" * 72)


# ---------------------------------------------------------------------------
# Step 4 — Final render
# ---------------------------------------------------------------------------

def render(video: str, board: list[dict], output: str,
           music: Optional[str], music_volume: float):
    """
    Render final video:
    - Only segments marked Keep or Change
    - Burn in captions with drawtext filter
    - Mix optional background music
    """
    print("\n[4/4] Rendering final video …")
    approved = [s for s in board if s["suggestion"] in ("Keep", "Change")]
    print(f"  Rendering {len(approved)} / {len(board)} segments "
          f"({sum(1 for s in board if s['suggestion']=='Drop')} dropped)")

    # Build concat list
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        list_path = f.name
        for seg in approved:
            f.write(f"file '{os.path.abspath(video)}'\n")
            f.write(f"inpoint {seg['start']:.6f}\n")
            f.write(f"outpoint {seg['end']:.6f}\n")

    # Pass 1: concat without captions
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
        concat_path = tf.name

    ffmpeg("-f", "concat", "-safe", "0", "-i", list_path,
           "-c", "copy", concat_path)
    os.unlink(list_path)

    # Pass 2: burn captions
    # Build a chain of drawtext filters
    filter_parts = []
    cursor = 0.0
    for seg in approved:
        dur   = seg["end"] - seg["start"]
        text  = seg["caption"].replace("'", "\\'").replace(":", r"\:")
        color = seg["font_color"].lstrip("#")
        bcolor = seg["brand_color"].lstrip("#")
        t_in  = round(cursor, 3)
        t_out = round(cursor + dur, 3)
        filter_parts.append(
            f"drawtext=text='{text}':fontcolor=0x{color}:fontsize=36:"
            f"box=1:boxcolor=0x{bcolor}@0.6:boxborderw=8:"
            f"x=(w-text_w)/2:y=h-th-40:"
            f"enable='between(t,{t_in},{t_out})'"
        )
        cursor += dur

    vf = ",".join(filter_parts) if filter_parts else "null"

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
        captioned_path = tf.name

    ffmpeg("-i", concat_path, "-vf", vf,
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", captioned_path)
    os.unlink(concat_path)

    # Pass 3 (optional): mix background music
    if music and os.path.exists(music):
        total_dur = probe_duration(captioned_path)
        ffmpeg("-i", captioned_path, "-stream_loop", "-1", "-i", music,
               "-filter_complex",
               f"[1:a]volume={music_volume},atrim=0:{total_dur}[music];"
               "[0:a][music]amix=inputs=2:duration=first[a]",
               "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-shortest", output)
        os.unlink(captioned_path)
    else:
        os.rename(captioned_path, output)

    print(f"\n✅  Final render → {output}")
    dur = probe_duration(output)
    print(f"    Duration: {dur:.1f}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_video",          help="Path to the raw input video")
    ap.add_argument("--pause-threshold",    type=float, default=0.1,
                    metavar="SECS",         help="Minimum pause length to cut (default 0.1)")
    ap.add_argument("--silence-db",         type=float, default=-40,
                    metavar="DB",           help="Volume level considered silence in dBFS (default -40)")
    ap.add_argument("--music",              default=None,  help="Background music file")
    ap.add_argument("--music-volume",       type=float, default=0.15)
    ap.add_argument("--brand-color",        default="#FF4444",
                    help="Primary brand color hex (default #FF4444)")
    ap.add_argument("--font-color",         default="#FFFFFF",
                    help="Caption font color hex (default #FFFFFF)")
    ap.add_argument("--approve",            action="store_true",
                    help="Skip storyboard approval and render immediately")
    ap.add_argument("--output-dir",         default="./out")
    ap.add_argument("--model",              default=None,
                    help="Path to whisper ggml model (auto-detected if omitted)")
    args = ap.parse_args()

    video = os.path.abspath(args.input_video)
    if not os.path.exists(video):
        sys.exit(f"Error: file not found: {video}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(video).stem

    # Locate whisper model
    model_path = args.model
    if not model_path:
        candidates = list(Path("tools/whisper.cpp/models").glob("ggml-*.bin"))
        if candidates:
            model_path = str(sorted(candidates)[0])
            print(f"  Auto-detected whisper model: {model_path}")
        else:
            sys.exit("Error: no whisper model found. Run ./setup.sh first, or pass --model.")

    # ------------------------------------------------------------------ #
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_tmp = tf.name

    try:
        # 1. Transcribe
        transcript = transcribe(video, model_path, wav_tmp)

        # 2. Detect pauses
        total_dur = probe_duration(video)
        pauses = detect_pauses(video, args.pause_threshold, args.silence_db)
        keep_segs = build_keep_segments(total_dur, pauses)

        print(f"\n  ✓ {len(pauses)} pauses cut "
              f"(total saved: {sum(p['duration'] for p in pauses):.1f}s)")

        # Cut pauses → intermediate file
        cut_path = str(out_dir / f"{stem}_cut.mp4")
        cut_pauses(video, keep_segs, cut_path, pauses)

        # 3. Storyboard
        board = build_storyboard(keep_segs, transcript,
                                 args.brand_color, args.font_color)

        storyboard_path = str(out_dir / f"{stem}_storyboard.json")
        with open(storyboard_path, "w") as f:
            json.dump(board, f, indent=2)
        print(f"  Storyboard saved → {storyboard_path}")

        print_storyboard(board)

        # --- Approval gate ---
        if not args.approve:
            print(f"""
┌─────────────────────────────────────────────────────────────┐
│  Storyboard ready. Edit {stem}_storyboard.json if needed.   │
│                                                             │
│  To render after approval, run:                             │
│    python3 edit.py {Path(video).name} --approve              │
│                                                             │
│  Or type 'yes' below to approve now and render.             │
└─────────────────────────────────────────────────────────────┘
""")
            answer = input("Approve storyboard and render? [yes/no]: ").strip().lower()
            if answer not in ("yes", "y"):
                print("  Render skipped. Edit the storyboard and re-run with --approve.")
                sys.exit(0)

        # 4. Render
        final_path = str(out_dir / f"{stem}_final.mp4")
        render(cut_path, board, final_path, args.music, args.music_volume)

    finally:
        for tmp in (wav_tmp, wav_tmp + ".json"):
            if os.path.exists(tmp):
                os.unlink(tmp)


if __name__ == "__main__":
    main()
