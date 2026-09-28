"""Spike: WebSocket receiver for 16 kHz mono PCM s16le audio.

Protocol on /ws/audio:
  1. Client sends text {"type": "start", "encoding": "pcm_s16le", "channels": 1, "sample_rate": 16000}.
  2. Server replies {"type": "ready", ...limits}.
  3. Client sends binary frames; server replies {"type": "ack", "frames", "samples", "duration_s"} per frame.
  4. Client sends text {"type": "stop"}; server replies {"type": "stopped", ...totals} and closes.
Any violation gets {"type": "error", "code", "message"} and the socket is closed.
Audio bytes are validated, counted and discarded; nothing is stored.
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
EXPECTED_FORMAT = {"encoding": "pcm_s16le", "channels": 1, "sample_rate": SAMPLE_RATE}
MAX_FRAME_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE  # at most 1 s of audio per frame
MAX_SESSION_SECONDS = 15 * 60
MAX_SESSIONS = 4
START_TIMEOUT_S = 10.0

app = FastAPI()
active_sessions = 0


def _json(text):
    try:
        body = json.loads(text) if text is not None else None
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def _fail(ws: WebSocket, code: str, message: str, close_code: int) -> None:
    await ws.send_json({"type": "error", "code": code, "message": message})
    await ws.close(code=close_code)


@app.websocket("/ws/audio")
async def audio(ws: WebSocket) -> None:
    global active_sessions
    await ws.accept()
    if active_sessions >= MAX_SESSIONS:
        await _fail(ws, "too_many_sessions", f"At most {MAX_SESSIONS} sessions at once.", 1013)
        return
    active_sessions += 1
    try:
        await _session(ws)
    except WebSocketDisconnect:
        pass
    finally:
        active_sessions -= 1


async def _session(ws: WebSocket) -> None:
    try:
        msg = await asyncio.wait_for(ws.receive(), START_TIMEOUT_S)
    except asyncio.TimeoutError:
        await _fail(ws, "start_timeout", "No start message received.", 1008)
        return
    if msg["type"] == "websocket.disconnect":
        return
    start = _json(msg.get("text"))
    if not start or start.get("type") != "start":
        await _fail(ws, "expected_start", "First message must be a JSON start message.", 1008)
        return
    declared = {key: start.get(key) for key in EXPECTED_FORMAT}
    if declared != EXPECTED_FORMAT:
        await _fail(ws, "unsupported_format", f"Expected {EXPECTED_FORMAT}, got {declared}.", 1003)
        return
    await ws.send_json({"type": "ready", **EXPECTED_FORMAT,
                        "max_frame_bytes": MAX_FRAME_BYTES, "max_session_seconds": MAX_SESSION_SECONDS})

    frames = samples = 0
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            return
        data = msg.get("bytes")
        if data is None:
            body = _json(msg.get("text"))
            if body and body.get("type") == "stop":
                await ws.send_json({"type": "stopped", "frames": frames, "samples": samples,
                                    "duration_s": samples / SAMPLE_RATE})
                await ws.close(code=1000)
                return
            await _fail(ws, "unexpected_text", "After start, send binary audio or a stop message.", 1003)
            return
        if not data:
            await _fail(ws, "empty_frame", "Audio frame is empty.", 1007)
            return
        if len(data) % BYTES_PER_SAMPLE:
            await _fail(ws, "misaligned_frame", f"Frame of {len(data)} bytes is not whole 16-bit samples.", 1007)
            return
        if len(data) > MAX_FRAME_BYTES:
            await _fail(ws, "frame_too_large", f"Frame exceeds {MAX_FRAME_BYTES} bytes.", 1009)
            return
        if samples + len(data) // BYTES_PER_SAMPLE > MAX_SESSION_SECONDS * SAMPLE_RATE:
            await _fail(ws, "session_limit", f"Session exceeds {MAX_SESSION_SECONDS} s of audio.", 1008)
            return
        frames += 1
        samples += len(data) // BYTES_PER_SAMPLE
        await ws.send_json({"type": "ack", "frames": frames, "samples": samples,
                            "duration_s": samples / SAMPLE_RATE})


# Serve the browser capture spike from the same origin so the page can reach /ws/audio.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend" / "spike", html=True))
