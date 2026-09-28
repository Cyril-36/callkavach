# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""Sarvam STT smoke test: send local WAV files to the REST endpoint, print transcript,
errors and measured round-trip latency. Synthetic or consented audio only.

Usage: uv run backend/spike/stt_smoke.py [--model saaras:v3] [--mode codemix] FILE:LANG ...
"""
import argparse
import os
import sys
import time
import wave
from pathlib import Path

import requests

URL = "https://api.sarvam.ai/speech-to-text"  # docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe


def load_key() -> str | None:
    if os.environ.get("SARVAM_API_KEY"):
        return os.environ["SARVAM_API_KEY"]
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("SARVAM_API_KEY=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def describe(path: Path) -> str:
    with wave.open(str(path)) as w:
        secs = w.getnframes() / w.getframerate()
        return f"{w.getframerate()} Hz, {w.getnchannels()} ch, {8 * w.getsampwidth()}-bit, {secs:.1f}s"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="saaras:v3")
    p.add_argument("--mode", default="codemix")
    p.add_argument("inputs", nargs="+", help="path:language_code, e.g. samples/a.wav:te-IN")
    args = p.parse_args()

    key = load_key()
    if not key:
        print("BLOCKED: SARVAM_API_KEY not set in environment or .env", file=sys.stderr)
        return 2

    failures = 0
    for item in args.inputs:
        path, lang = item.rsplit(":", 1)
        path = Path(path)
        print(f"\n== {path.name} [{lang}] {describe(path)} model={args.model} mode={args.mode}")
        start = time.perf_counter()
        try:
            with path.open("rb") as f:
                r = requests.post(
                    URL,
                    headers={"api-subscription-key": key},
                    files={"file": (path.name, f, "audio/wav")},
                    data={"model": args.model, "mode": args.mode, "language_code": lang},
                    timeout=60,
                )
        except requests.RequestException as e:
            print(f"ERROR: {e}")
            failures += 1
            continue
        ms = (time.perf_counter() - start) * 1000
        print(f"HTTP {r.status_code}  latency {ms:.0f} ms (round trip, includes upload)")
        if r.ok:
            body = r.json()
            print(f"language_code: {body.get('language_code')}  request_id: {body.get('request_id')}")
            print(f"transcript: {body.get('transcript')}")
            if not (body.get("transcript") or "").strip():
                print("ERROR: HTTP 200 but transcript is empty or missing")
                failures += 1
        else:
            print(f"ERROR body: {r.text[:500]}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
