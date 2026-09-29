# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13"]
# ///
"""Stream a 16 kHz mono 16-bit WAV through the running /ws/audio relay in real time and print
every event with its arrival time. Synthetic or consented audio only.

Usage: uv run backend/spike/relay_smoke.py FILE.wav LANG [--url ws://127.0.0.1:8766/ws/audio]
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relay_client import stream_wav  # noqa: E402


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("language_code")
    p.add_argument("--url", default="ws://127.0.0.1:8766/ws/audio")
    p.add_argument("--tail-silence", type=float, default=1.5, help="seconds of silence after the speech")
    args = p.parse_args()

    def show(entry):
        print(f"{entry['t']:6.2f}s  {json.dumps(entry['msg'], ensure_ascii=False)}")

    try:
        run = await stream_wav(args.url, args.wav, args.language_code, tail_silence=args.tail_silence, on_message=show)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    final = run["final"]
    segments = [m["msg"]["text"] for m in run["messages"] if m["msg"]["type"] == "transcript"]
    if run["stop_sent_t"] is not None:
        print(f"\nspeech audio {run['speech_s']:.1f}s; stop sent at {run['stop_sent_t']:.2f}s; "
              f"stopped/error at {run['end_t']:.2f}s ({run['end_t'] - run['stop_sent_t']:.2f}s after stop)")
    print("TRANSCRIPT:", " | ".join(segments) or "(none)")
    return 0 if final and final["type"] == "stopped" and final["transcription"] == "complete" and segments else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
