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
This app does not save recordings or transcripts: audio is held only in the bounded relay queue and is
sent to Sarvam for transcription (Sarvam's own retention is governed by its terms, not by this code).

Local-spike security: the Host header must be localhost, 127.0.0.1 or [::1] (stopping DNS rebinding),
and a browser Origin must match that host and port exactly; anything else is refused before any Sarvam
session is opened. Browsers always send Origin on WebSocket upgrades; non-browser clients (such as
relay_smoke.py) send none and are allowed on a trusted Host. An Origin check is not authentication - any non-browser client can set or omit
the header - so a public deployment additionally needs authentication and rate limits.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from detector import Segment, SessionDetector
from verifier_config import make_verifier
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
PROVIDER_CLOSE_TIMEOUT_S = 1.0  # bounded provider shutdown: 6 s + 1 s stays inside the browser's 8 s
connect_provider = default_connector()
verifier_factory = make_verifier  # returns (verifier, None) or (None, reason); replaced in tests

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


TRUSTED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})  # local spike only
_DEFAULT_PORTS = {"http": 80, "ws": 80, "https": 443, "wss": 443}


def _host_port(netloc: str, scheme: str):
    """(hostname, port) from a Host header or URL netloc, or None if it cannot be parsed."""
    try:
        parts = urlsplit(f"//{netloc}")
        port = parts.port or _DEFAULT_PORTS[scheme]
    except (ValueError, KeyError):
        return None
    if not parts.hostname or parts.username is not None or parts.password is not None:
        return None
    return parts.hostname.lower(), port


def _trusted_request(ws: WebSocket) -> bool:
    """Host must be a trusted local host; a browser Origin must be exactly that host and port.

    The Host allowlist stops DNS rebinding (an attacker's domain resolving to 127.0.0.1 would send a
    matching Host and Origin of that domain). Clients without an Origin (non-browser, e.g.
    relay_smoke.py) are accepted only on a trusted Host.
    """
    host = _host_port(ws.headers.get("host", ""), ws.url.scheme)
    if host is None or host[0] not in TRUSTED_HOSTS:
        return False
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or parts.path not in ("", "/") or parts.query or parts.fragment:
        return False
    return _host_port(parts.netloc, parts.scheme) == host


@app.websocket("/ws/audio")
async def audio(ws: WebSocket) -> None:
    global active_sessions
    if not _trusted_request(ws):
        await ws.close(code=1008)  # before accept: the upgrade is refused with HTTP 403, no session is opened
        return
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
        self.close_task = None
        self.detector = None  # SessionDetector, or None when analysis is unavailable
        self.detector_unavailable = None  # reason, when there is no detector
        self.started_at = asyncio.get_running_loop().time()
        self.failed = asyncio.Event()
        self.failure = None
        self.lock = asyncio.Lock()

    async def send(self, msg: dict) -> None:
        async with self.lock:
            if self.failure and msg.get("code") != "provider_error":
                return  # socket already closed after a provider failure
            await self.ws.send_json(msg)

    def session_ms(self) -> int:
        return int((asyncio.get_running_loop().time() - self.started_at) * 1000)

    async def send_built(self, build) -> None:
        """Send an event whose timestamps are taken at the real send boundary: after the send lock is held,
        immediately before the WebSocket write (used for detector risk events)."""
        async with self.lock:
            if self.failure:
                return
            await self.ws.send_json(build(self.session_ms()))

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

    def close_provider(self) -> asyncio.Future:
        """Start closing the provider once; the task runs on its own, so waits on it can be bounded."""
        if self.close_task is None:
            self.close_task = asyncio.ensure_future(self.provider.close())
        return self.close_task

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
                if self.detector:  # finalized segments only, in arrival order; no speaker or other metadata
                    self.detector.add(Segment.from_event(event, self.session_ms()))
                continue
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
    verifier, relay.detector_unavailable = verifier_factory()
    if verifier:  # one session clock for segment receive times and risk emission times
        relay.detector = SessionDetector(verifier, send=relay.send_built, clock=relay.session_ms)
    tasks = [asyncio.create_task(relay.guard(relay.pump())), asyncio.create_task(relay.guard(relay.read()))]
    try:
        await relay.send({"type": "ready", **EXPECTED_FORMAT, "language_code": language,
                          "max_frame_bytes": MAX_FRAME_BYTES, "max_session_seconds": MAX_SESSION_SECONDS})
        if relay.detector_unavailable:  # visible from the start: transcription runs, scam analysis does not
            await relay.send({"type": "risk", "level": "none", "reason": None, "analysis": "unavailable",
                              "error": relay.detector_unavailable, "tactics": [], "analysed_segments": 0,
                              "unanalysed_segments": 0, "calls": 0, "latency_s": None})
        await _receive_audio(ws, relay)
    finally:
        relay.closing = True
        for t in tasks:
            t.cancel()
        # Start every close before the first await: if this session is being cancelled, the first await
        # raises at once, and anything not yet started would never run. Waiting is bounded.
        closers = [relay.close_provider()]
        if relay.detector:
            closers.append(asyncio.ensure_future(relay.detector.close()))
        if verifier:
            closers.append(asyncio.ensure_future(verifier.close()))
        await asyncio.wait([*closers, *tasks], timeout=PROVIDER_CLOSE_TIMEOUT_S)


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
    # Transcription settles first; scam analysis of the final segments then gets the rest of the same deadline.
    while not relay.failure and loop.time() < deadline and not (
            relay.settled(loop.time()) and (relay.detector is None or relay.detector.idle())):
        await asyncio.sleep(0.05)
    if relay.failure:
        return  # provider_failed already reported the error and closed the socket
    reasons = relay.incomplete_reasons()
    if not relay.settled(loop.time()) and not reasons:
        # Every expected final arrived, but the provider was still sending when the deadline passed.
        reasons.append(f"the transcription provider had not settled within {FINALIZE_DEADLINE_S:g} s of stopping")
    relay.closing = True
    close = relay.close_provider()
    await asyncio.wait([close], timeout=PROVIDER_CLOSE_TIMEOUT_S)
    cleanup = "timeout" if not close.done() else ("error" if close.exception() else "ok")
    await relay.send({"type": "stopped", "frames": frames, "samples": samples, "duration_s": samples / SAMPLE_RATE,
                      "segments": relay.segments, "utterances": relay.utterances_started,
                      "finals_before_flush": relay.finals_before_flush, "finals_after_flush": relay.finals_after_flush,
                      "dropped_s": relay.dropped_samples / SAMPLE_RATE,
                      "transcription": "incomplete" if reasons else "complete",
                      "reason": "; ".join(reasons) or None,
                      "provider_cleanup": cleanup,
                      "analysis": relay.detector.summary() if relay.detector else
                      {"status": "unavailable", "error": relay.detector_unavailable}})
    await ws.close(code=1000)


# Serve the browser capture spike from the same origin so the page can reach /ws/audio.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend" / "spike", html=True))
