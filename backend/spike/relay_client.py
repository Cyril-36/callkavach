"""Client side of /ws/audio, shared by relay_smoke.py (manual check) and e2e_harness.py (repeatable runs).

stream_wav() streams a 16 kHz mono 16-bit WAV in real time, sends Stop, and returns every non-ack message
with its client-side arrival time plus the client's own timing marks. Synthetic or consented audio only.
"""
import asyncio
import json
import time
import wave

import websockets

FRAME = 1600  # 100 ms at 16 kHz


def read_wav(path: str) -> bytes:
    with wave.open(path) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"{path}: WAV must be 16 kHz mono 16-bit")
        return w.readframes(w.getnframes())


async def stream_wav(url: str, wav_path: str, language_code: str, *, tail_silence: float = 1.5,
                     on_message=None, headers=None) -> dict:
    """Returns {"messages": [{"t": seconds_since_connect, "msg": {...}}], "speech_s", "speech_end_t",
    "stop_sent_t", "end_t", "final"} where final is the stopped/error message or None."""
    speech = read_wav(wav_path)
    pcm = speech + b"\x00\x00" * int(16000 * tail_silence)
    speech_bytes = len(speech)
    messages = []
    marks = {"speech_end_t": None, "stop_sent_t": None}
    async with websockets.connect(url, additional_headers=headers, max_size=2**22) as ws:
        t0 = time.perf_counter()
        at = lambda: round(time.perf_counter() - t0, 3)

        def record(msg):
            entry = {"t": at(), "msg": msg}
            messages.append(entry)
            if on_message:
                on_message(entry)

        await ws.send(json.dumps({"type": "start", "encoding": "pcm_s16le", "channels": 1,
                                  "sample_rate": 16000, "language_code": language_code}))
        ready = json.loads(await ws.recv())
        record(ready)
        if ready["type"] != "ready":
            return {"messages": messages, "speech_s": speech_bytes / 32000, "final": ready, "end_t": at(), **marks}

        async def reader():
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg["type"] == "ack":
                        continue
                    record(msg)
                    if msg["type"] in ("stopped", "error"):
                        return msg
            except websockets.ConnectionClosed:
                return None

        read_task = asyncio.create_task(reader())
        for i in range(0, len(pcm), FRAME * 2):
            if read_task.done():
                break  # the server ended the session (for example a provider error)
            await ws.send(pcm[i:i + FRAME * 2])
            if marks["speech_end_t"] is None and i + FRAME * 2 >= speech_bytes:
                marks["speech_end_t"] = at()
            await asyncio.sleep(0.1)  # real-time pacing
        if not read_task.done():
            marks["stop_sent_t"] = at()
            await ws.send(json.dumps({"type": "stop"}))
        final = await read_task
        return {"messages": messages, "speech_s": speech_bytes / 32000, "final": final, "end_t": at(), **marks}
