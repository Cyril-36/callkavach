"""Spike: WebSocket receiver for 16 kHz mono PCM s16le audio, relayed to realtime STT.

Protocol on /ws/audio:
  1. Client sends text {"type": "start", "encoding": "pcm_s16le", "channels": 1, "sample_rate": 16000,
     "language_code": "te-IN" | "hi-IN" | "en-IN"}.
  2. Server opens the STT provider session, then replies {"type": "ready", ...limits}.
  3. Client sends binary frames; server replies {"type": "ack", "frames", "samples", "duration_s"} per frame
     and relays the audio to the provider through a bounded queue. If the queue is full the frame is
     dropped and the client gets {"type": "gap", ...}.
  4. Provider results arrive as {"type": "speech", "state"} and {"type": "transcript", "final", "segment_id",
     "text", ...}; each final segment is forwarded once.
  5. Client sends {"type": "stop"}; server delivers all queued audio, then flushes the provider, waits for
     every started utterance's final transcript, closes the provider and replies
     {"type": "stopped", ..., "transcription": "complete" | "incomplete", "reason"}.
Sarvam (probed 2026-09-29) sends START_SPEECH, END_SPEECH and one final transcript per utterance, and sends
nothing in reply to a flush when no utterance is open. Completion is therefore judged by utterance
accounting: every START_SPEECH must have a final result, after the flush was actually sent.
Any violation or provider failure gets {"type": "error", "code", "message"} and the socket is closed.
Audio is held only in the bounded relay queue; nothing is stored.
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from stt_provider import ProviderError, default_connector

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
EXPECTED_FORMAT = {"encoding": "pcm_s16le", "channels": 1, "sample_rate": SAMPLE_RATE}
LANGUAGES = ("te-IN", "hi-IN", "en-IN")
MAX_FRAME_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE  # at most 1 s of audio per frame
MAX_SESSION_SECONDS = 15 * 60
MAX_SESSIONS = 4
START_TIMEOUT_S = 10.0
MAX_QUEUED_SECONDS = 5.0  # audio waiting to reach the provider; beyond this, frames are dropped
FINALIZE_DEADLINE_S = 6.0  # whole Stop budget on the server: drain, flush, final results. Browser waits 8 s.
FINALIZE_SETTLE_S = 1.0  # after the flush, the provider must be quiet this long with nothing open
connect_provider = default_connector()

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


def provider_event(msg: dict):
    """Translate a provider message into a browser event, None to ignore it, or raise ProviderError."""
    kind, data = msg.get("type"), msg.get("data") or {}
    if kind == "data":
        metrics = data.get("metrics") or {}
        return {"type": "transcript", "final": True, "segment_id": data.get("request_id"),
                "text": (data.get("transcript") or "").strip(), "language_code": data.get("language_code"),
                "audio_duration_s": metrics.get("audio_duration"),
                "processing_latency_s": metrics.get("processing_latency")}
    if kind == "events" and data.get("signal_type") in ("START_SPEECH", "END_SPEECH"):
        return {"type": "speech", "state": "started" if data["signal_type"] == "START_SPEECH" else "ended"}
    if kind == "error":
        raise ProviderError(f"{data.get('code') or 'error'}: {data.get('error') or data.get('message') or msg}")
    return None


_FLUSH = object()


class _Relay:
    """Moves audio to the provider and provider results back to the browser."""

    def __init__(self, ws: WebSocket, provider):
        self.ws, self.provider = ws, provider
        self.queue = asyncio.Queue()  # bounded by queued_samples, not item count
        self.queued_samples = self.dropped_samples = self.segments = 0
        self.seen = set()  # forwarded (non-empty) final segment IDs
        self.final_ids = set()  # every distinct final result, including empty ones
        self.utterances_started = 0  # START_SPEECH count; each needs one final result
        self.finals_before_flush = self.finals_after_flush = 0
        self.flush_sent_at = None  # loop time when the flush actually went to the provider
        self.last_event_at = asyncio.get_running_loop().time()
        self.closing = False
        self.failed = asyncio.Event()
        self.failure = None
        self.lock = asyncio.Lock()

    async def send(self, msg: dict) -> None:
        async with self.lock:
            if self.failure and msg.get("code") != "provider_error":
                return  # socket already closed after a provider failure
            await self.ws.send_json(msg)

    def incomplete_reasons(self) -> list[str]:
        """Why transcription cannot be called complete right now; empty means complete."""
        reasons = []
        if self.flush_sent_at is None:
            reasons.append(f"{self.queued_samples / SAMPLE_RATE:.2f} s of accepted audio had not reached the "
                           "transcription provider")
        if self.dropped_samples:
            reasons.append(f"{self.dropped_samples / SAMPLE_RATE:.2f} s of audio was dropped before transcription")
        finals = len(self.final_ids)
        if self.utterances_started > finals:
            reasons.append(f"{self.utterances_started - finals} utterance(s) had no final transcript")
        elif finals > self.utterances_started:
            reasons.append("speech-detection signals were missing or inconsistent, so it cannot be confirmed "
                           "that every utterance was transcribed")
        elif finals == 0:
            reasons.append("no speech was detected, so transcription cannot be confirmed")
        return reasons

    def settled(self, now: float) -> bool:
        """Flush sent, nothing open, and the provider quiet for the settle period since the later of both."""
        if self.flush_sent_at is None or self.utterances_started > len(self.final_ids):
            return False
        return now - max(self.flush_sent_at, self.last_event_at) >= FINALIZE_SETTLE_S

    def enqueue(self, frame: bytes) -> bool:
        n = len(frame) // BYTES_PER_SAMPLE
        if self.queued_samples + n > MAX_QUEUED_SECONDS * SAMPLE_RATE:
            self.dropped_samples += n
            return False
        self.queued_samples += n
        self.queue.put_nowait(frame)
        return True

    async def pump(self) -> None:
        # FIFO: every frame accepted before Stop reaches the provider before the flush does.
        while (item := await self.queue.get()) is not _FLUSH:
            await self.provider.send_audio(item)
            self.queued_samples -= len(item) // BYTES_PER_SAMPLE
        await self.provider.flush()
        self.flush_sent_at = asyncio.get_running_loop().time()

    async def read(self) -> None:
        async for msg in self.provider.events():
            self.last_event_at = asyncio.get_running_loop().time()
            event = provider_event(msg)
            if event is None:
                continue
            if event["type"] == "speech":
                if event["state"] == "started":
                    self.utterances_started += 1
                await self.send(event)
                continue
            if event["final"]:
                if event["segment_id"] in self.final_ids:
                    continue  # duplicate delivery of a result already counted
                self.final_ids.add(event["segment_id"])
                if self.flush_sent_at is None:
                    self.finals_before_flush += 1
                else:
                    self.finals_after_flush += 1
                if not event["text"]:
                    continue  # utterance was not speech; counted, not shown
                self.seen.add(event["segment_id"])
                self.segments += 1
            await self.send(event)
        if not self.closing:
            raise ProviderError("provider closed the connection")

    async def guard(self, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.provider_failed(str(e) or type(e).__name__)

    async def provider_failed(self, message: str) -> None:
        if self.closing or self.failure:
            return
        self.failure = message
        self.failed.set()
        try:
            await self.send({"type": "error", "code": "provider_error", "message": f"Transcription failed: {message}"})
            await self.ws.close(code=1011)
        except Exception:
            pass  # browser already gone


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
    language = start.get("language_code")
    if language not in LANGUAGES:
        await _fail(ws, "unsupported_language", f"language_code must be one of {LANGUAGES}, got {language!r}.", 1003)
        return
    try:
        provider = await connect_provider(language)
    except ProviderError as e:
        await _fail(ws, "provider_unavailable", f"Transcription unavailable: {e}", 1011)
        return

    relay = _Relay(ws, provider)
    tasks = [asyncio.create_task(relay.guard(relay.pump())), asyncio.create_task(relay.guard(relay.read()))]
    try:
        await relay.send({"type": "ready", **EXPECTED_FORMAT, "language_code": language,
                          "max_frame_bytes": MAX_FRAME_BYTES, "max_session_seconds": MAX_SESSION_SECONDS})
        await _receive_audio(ws, relay)
    finally:
        relay.closing = True
        for t in tasks:
            t.cancel()
        # Started as its own task so the provider is closed even if this session is being cancelled.
        closing = asyncio.ensure_future(provider.close())
        await asyncio.shield(asyncio.gather(closing, *tasks, return_exceptions=True))


async def _receive_audio(ws: WebSocket, relay: _Relay) -> None:
    frames = samples = 0
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect" or relay.failure:
            return
        data = msg.get("bytes")
        if data is None:
            body = _json(msg.get("text"))
            if body and body.get("type") == "stop":
                await _finish(ws, relay, frames, samples)
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
        n = len(data) // BYTES_PER_SAMPLE
        samples += n
        if not relay.enqueue(data):
            await relay.send({"type": "gap", "source": "server", "samples": n, "duration_s": n / SAMPLE_RATE,
                              "total_dropped_s": relay.dropped_samples / SAMPLE_RATE})
        await relay.send({"type": "ack", "frames": frames, "samples": samples, "duration_s": samples / SAMPLE_RATE})


async def _finish(ws: WebSocket, relay: _Relay, frames: int, samples: int) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + FINALIZE_DEADLINE_S
    relay.queue.put_nowait(_FLUSH)  # queued after every accepted frame
    while not relay.failure and not relay.settled(loop.time()) and loop.time() < deadline:
        await asyncio.sleep(0.05)
    if relay.failure:
        return  # provider_failed already reported the error and closed the socket
    reasons = relay.incomplete_reasons()
    relay.closing = True
    await relay.provider.close()
    await relay.send({"type": "stopped", "frames": frames, "samples": samples, "duration_s": samples / SAMPLE_RATE,
                      "segments": relay.segments, "utterances": relay.utterances_started,
                      "finals_before_flush": relay.finals_before_flush, "finals_after_flush": relay.finals_after_flush,
                      "dropped_s": relay.dropped_samples / SAMPLE_RATE,
                      "transcription": "incomplete" if reasons else "complete",
                      "reason": "; ".join(reasons) or None})
    await ws.close(code=1000)


# Serve the browser capture spike from the same origin so the page can reach /ws/audio.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend" / "spike", html=True))
