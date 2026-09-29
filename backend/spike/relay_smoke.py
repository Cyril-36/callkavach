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
import time
import wave

import websockets

FRAME = 1600  # 100 ms at 16 kHz


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("language_code")
    p.add_argument("--url", default="ws://127.0.0.1:8766/ws/audio")
    p.add_argument("--tail-silence", type=float, default=1.5, help="seconds of silence after the speech")
    args = p.parse_args()

    with wave.open(args.wav) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            print("WAV must be 16 kHz mono 16-bit", file=sys.stderr)
            return 2
        pcm = w.readframes(w.getnframes())
    pcm += b"\x00\x00" * int(16000 * args.tail_silence)
    speech_s = (len(pcm) // 2) / 16000 - args.tail_silence

    async with websockets.connect(args.url) as ws:
        t0 = time.perf_counter()
        at = lambda: time.perf_counter() - t0
        await ws.send(json.dumps({"type": "start", "encoding": "pcm_s16le", "channels": 1,
                                  "sample_rate": 16000, "language_code": args.language_code}))
        ready = json.loads(await ws.recv())
        print(f"{at():6.2f}s  {ready['type']}  {ready.get('message', '')}")
        if ready["type"] != "ready":
            return 1

        speech_end = None
        stop_sent = None
        segments = []

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg["type"] == "ack":
                    continue
                note = ""
                if msg["type"] == "transcript":
                    segments.append(msg["text"])
                    if speech_end is not None:
                        note = f"  [{at() - speech_end:.2f}s after speech audio ended; provider processing {msg['processing_latency_s']}s]"
                print(f"{at():6.2f}s  {json.dumps(msg, ensure_ascii=False)}{note}")
                if msg["type"] in ("stopped", "error"):
                    return msg

        read_task = asyncio.create_task(reader())
        for i in range(0, len(pcm), FRAME * 2):
            await ws.send(pcm[i:i + FRAME * 2])
            if speech_end is None and i + FRAME * 2 >= len(pcm) - int(16000 * args.tail_silence) * 2:
                speech_end = at()
            await asyncio.sleep(0.1)  # real-time pacing
        stop_sent = at()
        await ws.send(json.dumps({"type": "stop"}))
        final = await read_task
        print(f"\nspeech audio {speech_s:.1f}s; stop sent at {stop_sent:.2f}s; "
              f"stopped/error at {at():.2f}s ({at() - stop_sent:.2f}s after stop)")
        print("TRANSCRIPT:", " | ".join(segments) or "(none)")
        return 0 if final and final["type"] == "stopped" and final["transcription"] == "complete" and segments else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
