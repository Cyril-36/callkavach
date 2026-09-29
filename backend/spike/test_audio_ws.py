import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

import audio_ws
from detector import VerifierError as VerifierErrorForTest
from stt_provider import ProviderError

START = {"type": "start", "encoding": "pcm_s16le", "channels": 1, "sample_rate": 16000, "language_code": "te-IN"}


def data(request_id, text, duration=1.0, latency=0.3):
    return {"type": "data", "data": {"request_id": request_id, "transcript": text, "language_code": "te-IN",
                                     "metrics": {"audio_duration": duration, "processing_latency": latency}}}


def signal(kind):
    return {"type": "events", "data": {"signal_type": kind}}


class FakeProvider:
    """Scripted provider. on_audio(provider, total_bytes) and on_flush(provider) may emit events.

    Without callbacks it behaves like Sarvam: START_SPEECH on the first audio, and on flush the
    open utterance's END_SPEECH and final result. `log` records audio and flush in arrival order.
    """

    instances = []

    def __init__(self, on_audio=None, on_flush=None, block_audio=False, audio_delay=0.0, close_delay=0.0,
                 close_error=False):
        self.out = asyncio.Queue()
        self.audio = bytearray()
        self.log = []
        self.flushed = self.closed = self.open_utterance = False
        self.on_audio, self.on_flush = on_audio, on_flush
        self.block_audio, self.audio_delay = block_audio, audio_delay
        self.close_delay, self.close_error = close_delay, close_error
        self.close_called = False
        FakeProvider.instances.append(self)

    def emit(self, *msgs):
        for m in msgs:
            self.out.put_nowait(m)

    async def send_audio(self, pcm):
        if self.block_audio:
            await asyncio.Event().wait()  # provider never accepts audio
        if self.audio_delay:
            await asyncio.sleep(self.audio_delay)
        self.audio.extend(pcm)
        self.log.append(("audio", len(pcm)))
        if self.on_audio:
            self.on_audio(self, len(self.audio))
        elif not self.open_utterance:
            self.open_utterance = True
            self.emit(signal("START_SPEECH"))

    async def flush(self):
        self.flushed = True
        self.log.append(("flush",))
        if self.on_flush:
            self.on_flush(self)
        elif self.open_utterance:
            self.open_utterance = False
            self.emit(signal("END_SPEECH"), data(f"flush-{len(self.log)}", "flushed utterance"))

    async def events(self):
        while (m := await self.out.get()) is not None:
            if isinstance(m, Exception):
                raise m
            yield m

    async def close(self):
        self.close_called = True
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        if self.close_error:
            raise ConnectionError("close handshake failed")
        self.closed = True
        self.out.put_nowait(None)


def use_provider(monkeypatch, **kwargs):
    async def connect(language_code):
        return FakeProvider(**kwargs)
    monkeypatch.setattr(audio_ws, "connect_provider", connect)


class RecordingVerifier:
    """Detector verifier for relay tests. respond(request) -> findings; records every request."""

    instances = []

    def __init__(self, respond=None, delay=0.0):
        self.respond = respond or (lambda request: [])
        self.delay = delay
        self.requests = []
        self.closed = False
        self.completed = self.cancelled = 0
        RecordingVerifier.instances.append(self)

    async def analyse(self, request):
        self.requests.append(request)
        if self.delay:
            try:
                await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        self.completed += 1
        result = self.respond(request)
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        self.closed = True


def use_verifier(monkeypatch, respond=None, delay=0.0):
    monkeypatch.setattr(audio_ws, "verifier_factory", lambda: (RecordingVerifier(respond, delay), None))


@pytest.fixture(autouse=True)
def default_provider(monkeypatch):
    FakeProvider.instances.clear()
    RecordingVerifier.instances.clear()
    use_provider(monkeypatch)
    use_verifier(monkeypatch)  # never the real Gemini configuration in tests
    monkeypatch.setattr(audio_ws, "FINALIZE_SETTLE_S", 0.05)
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 2.0)


class LocalClient:
    """TestClient sends Host: testserver for WebSockets (base_url is ignored), which the relay refuses.
    Default every connection to a trusted local Host, like a browser on http://127.0.0.1:8766."""

    def __init__(self):
        self._client = TestClient(audio_ws.app)

    def websocket_connect(self, url, headers=None):
        return self._client.websocket_connect(url, headers={"host": "127.0.0.1:8766", **(headers or {})})


@pytest.fixture
def client():
    return LocalClient()


def open_session(ws, start=START):
    ws.send_json(start)
    ready = ws.receive_json()
    assert ready["type"] == "ready", ready
    return ready


def receive_until(ws, kind):
    """Collect messages until one of the given type; returns (that message, all collected)."""
    seen = []
    while True:
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == kind:
            return msg, seen


def expect_error(ws, code, close_code):
    msg, _ = receive_until(ws, "error")
    assert msg["code"] == code, msg
    with pytest.raises(WebSocketDisconnect) as closed:
        while True:
            ws.receive_json()
    assert closed.value.code == close_code
    return msg


def wait_until(pred, what):
    for _ in range(200):
        if pred():
            return
        time.sleep(0.01)
    pytest.fail(what)


def wait_for_no_sessions():
    wait_until(lambda: audio_ws.active_sessions == 0, f"{audio_ws.active_sessions} session(s) still active")


# --- receiver behaviour (unchanged contract) ---

def test_valid_frames_are_acknowledged_and_relayed(client):
    with client.websocket_connect("/ws/audio") as ws:
        ready = open_session(ws)
        assert ready["max_frame_bytes"] == 32000 and ready["language_code"] == "te-IN"
        ws.send_bytes(b"\x01\x00" * 1600)
        assert receive_until(ws, "ack")[0] == {"type": "ack", "frames": 1, "samples": 1600, "duration_s": 0.1}
        ws.send_bytes(b"\x02\x00" * 16000)
        assert receive_until(ws, "ack")[0] == {"type": "ack", "frames": 2, "samples": 17600, "duration_s": 1.1}
        ws.send_json({"type": "stop"})
        stopped, _ = receive_until(ws, "stopped")
        assert stopped["samples"] == 17600 and stopped["transcription"] == "complete"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1000
    provider = FakeProvider.instances[0]
    assert bytes(provider.audio) == b"\x01\x00" * 1600 + b"\x02\x00" * 16000, "audio not relayed byte-for-byte"
    assert provider.flushed and provider.closed
    wait_for_no_sessions()


@pytest.mark.parametrize("bad", [
    {**START, "sample_rate": 48000},
    {**START, "channels": 2},
    {**START, "encoding": "pcm_f32le"},
    {"type": "start"},
])
def test_unsupported_format_is_rejected(client, bad):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json(bad)
        expect_error(ws, "unsupported_format", 1003)
    assert not FakeProvider.instances, "provider opened for a rejected session"


@pytest.mark.parametrize("language", [None, "ta-IN", "unknown"])
def test_unsupported_language_is_rejected(client, language):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({**START, "language_code": language})
        expect_error(ws, "unsupported_language", 1003)


@pytest.mark.parametrize("first", ["not json", '["start"]', '{"type": "hello"}'])
def test_first_message_must_be_start(client, first):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text(first)
        expect_error(ws, "expected_start", 1008)


def test_audio_before_start_is_rejected(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(b"\x00\x00" * 10)
        expect_error(ws, "expected_start", 1008)


@pytest.mark.parametrize("frame,code,close_code", [
    (b"", "empty_frame", 1007),
    (b"\x00\x00\x00", "misaligned_frame", 1007),
    (b"\x00\x00" * 16001, "frame_too_large", 1009),
])
def test_invalid_frames_are_rejected(client, frame, code, close_code):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(frame)
        expect_error(ws, code, close_code)
    wait_until(lambda: FakeProvider.instances[0].closed, "provider not closed")


def test_unexpected_text_after_start_is_rejected(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_text("hello")
        expect_error(ws, "unexpected_text", 1003)


def test_session_audio_limit(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "MAX_SESSION_SECONDS", 1)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 16000)
        assert receive_until(ws, "ack")[0]["samples"] == 16000
        ws.send_bytes(b"\x00\x00")
        expect_error(ws, "session_limit", 1008)


def test_start_timeout(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "START_TIMEOUT_S", 0.05)
    with client.websocket_connect("/ws/audio") as ws:
        expect_error(ws, "start_timeout", 1008)


def test_concurrent_session_limit(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "MAX_SESSIONS", 1)
    with client.websocket_connect("/ws/audio") as first:
        open_session(first)
        with client.websocket_connect("/ws/audio") as second:
            expect_error(second, "too_many_sessions", 1013)
    wait_for_no_sessions()


def test_client_disconnect_mid_session_closes_provider(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 800)
        assert receive_until(ws, "ack")[0]["samples"] == 800
        assert audio_ws.active_sessions == 1
    wait_for_no_sessions()
    wait_until(lambda: FakeProvider.instances[0].closed, "provider not closed after client disconnect")


def test_second_session_starts_fresh(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 4000)
        assert receive_until(ws, "ack")[0]["samples"] == 4000
    wait_for_no_sessions()
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 160)
        assert receive_until(ws, "ack")[0] == {"type": "ack", "frames": 1, "samples": 160, "duration_s": 0.01}
    assert len(FakeProvider.instances) == 2 and FakeProvider.instances[0] is not FakeProvider.instances[1]


# --- transcription relay ---

def test_provider_unavailable_is_reported(client, monkeypatch):
    async def connect(language_code):
        raise ProviderError("SARVAM_API_KEY is not configured on the server")
    monkeypatch.setattr(audio_ws, "connect_provider", connect)
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json(START)
        msg = expect_error(ws, "provider_unavailable", 1011)
    assert "not configured" in msg["message"]


def test_speech_events_and_final_segments_are_forwarded_once(client):
    def speak(p, total):
        if total == 3200:
            p.emit(signal("START_SPEECH"))
        if total == 6400:
            p.emit(signal("END_SPEECH"), data("seg-1", "నేను Inspector Sharma"), data("seg-1", "నేను Inspector Sharma"),
                   signal("START_SPEECH"), signal("END_SPEECH"), data("seg-noise", "  "))  # noise: empty final
    with client.websocket_connect("/ws/audio") as ws:
        FakeProvider.instances.clear()
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak
        events = []
        for _ in range(2):
            ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": "stop"})
        stopped, events = receive_until(ws, "stopped")
    transcripts = [e for e in events if e["type"] == "transcript"]
    assert transcripts == [{"type": "transcript", "final": True, "segment_id": "seg-1", "text": "నేను Inspector Sharma",
                            "language_code": "te-IN", "audio_duration_s": 1.0, "processing_latency_s": 0.3}]
    assert [e["state"] for e in events if e["type"] == "speech"] == ["started", "ended", "started", "ended"]
    assert stopped["segments"] == 1 and stopped["utterances"] == 2
    assert stopped["transcription"] == "complete" and stopped["reason"] is None


def test_stop_flushes_and_waits_for_the_final_transcript(client):
    def speak(p, total):
        if total == 3200:
            p.emit(signal("START_SPEECH"))
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = speak
        provider.on_flush = lambda p: p.emit(data("seg-final", "call లోనే ఉండండి"))
        ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": "stop"})
        stopped, events = receive_until(ws, "stopped")
    assert any(e.get("text") == "call లోనే ఉండండి" for e in events), "final transcript not delivered before stopped"
    assert stopped["transcription"] == "complete" and stopped["segments"] == 1
    assert stopped["finals_before_flush"] == 0 and stopped["finals_after_flush"] == 1
    assert provider.flushed and provider.closed


def test_stop_without_final_transcript_is_incomplete(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 0.3)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = lambda p, total: p.emit(signal("START_SPEECH"))
        ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": "stop"})
        stopped, _ = receive_until(ws, "stopped")
    assert stopped["transcription"] == "incomplete"
    assert "1 utterance(s) had no final transcript" in stopped["reason"]
    assert FakeProvider.instances[0].flushed and FakeProvider.instances[0].closed


@pytest.mark.parametrize("failure", [
    {"type": "error", "data": {"error": "Invalid audio", "code": "bad_request"}},
    ProviderError("Sarvam connection closed unexpectedly (code 1011)"),
    None,  # provider stream ends without being asked to close
])
def test_provider_failure_mid_session_is_reported(client, failure):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = lambda p, total: p.emit(failure)
        ws.send_bytes(b"\x00\x00" * 1600)
        msg = expect_error(ws, "provider_error", 1011)
    assert msg["message"].startswith("Transcription failed:")
    wait_for_no_sessions()
    wait_until(lambda: provider.closed, "provider not closed after failure")


def test_provider_failure_during_stop_is_not_reported_as_stopped(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = lambda p, total: p.emit(signal("START_SPEECH"))
        provider.on_flush = lambda p: p.emit({"type": "error", "data": {"error": "flush failed", "code": "internal"}})
        ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": "stop"})
        _, events = receive_until(ws, "error")
    assert not any(e["type"] == "stopped" for e in events)


def test_slow_provider_drops_audio_as_a_reported_gap(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "MAX_QUEUED_SECONDS", 0.25)
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 0.3)
    use_provider(monkeypatch, block_audio=True)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        gaps = []
        for _ in range(5):  # 0.5 s sent; the provider accepts nothing, the queue holds at most 0.25 s
            ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": "stop"})
        stopped, events = receive_until(ws, "stopped")
        gaps = [e for e in events if e["type"] == "gap"]
    assert gaps and all(g["source"] == "server" for g in gaps)
    # Frames count against the cap until the provider accepts them: two fit (one in flight), three are dropped.
    assert gaps[-1]["total_dropped_s"] == pytest.approx(0.3)
    assert stopped["transcription"] == "incomplete" and stopped["dropped_s"] == pytest.approx(0.3)
    assert "dropped" in stopped["reason"] and "had not reached" in stopped["reason"]
    assert not FakeProvider.instances[0].flushed, "flushed before queued audio was delivered"


def test_provider_event_translation():
    assert audio_ws.provider_event(signal("START_SPEECH")) == {"type": "speech", "state": "started"}
    assert audio_ws.provider_event({"type": "events", "data": {"signal_type": "OTHER"}}) is None
    assert audio_ws.provider_event({"type": "unknown"}) is None
    with pytest.raises(ProviderError, match="quota: Rate limited"):
        audio_ws.provider_event({"type": "error", "data": {"error": "Rate limited", "code": "quota"}})


# --- Stop finalization (utterance accounting) ---

def stop_and_collect(ws, frames=1, frame_samples=1600):
    for _ in range(frames):
        ws.send_bytes(b"\x00\x00" * frame_samples)
    ws.send_json({"type": "stop"})
    return receive_until(ws, "stopped")


def test_delayed_earlier_transcript_is_not_taken_as_the_final_result(client):
    """Two utterances; only the first one's (late) result arrives after the flush."""
    def speak(p, total):
        if total == 3200:
            p.emit(signal("START_SPEECH"))
        elif total == 6400:
            p.emit(signal("END_SPEECH"))  # utterance 1 ended; its result is still being processed
        elif total == 9600:
            p.emit(signal("START_SPEECH"))  # utterance 2 is open when Stop arrives
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = speak
        provider.on_flush = lambda p: p.emit(data("utt-1", "earlier utterance, delivered late"))
        stopped, events = stop_and_collect(ws, frames=3)
    assert any(e.get("text") == "earlier utterance, delivered late" for e in events)
    assert stopped["utterances"] == 2 and stopped["finals_after_flush"] == 1
    assert stopped["transcription"] == "incomplete"
    assert "1 utterance(s) had no final transcript" in stopped["reason"]


def test_missing_final_after_end_of_speech_is_incomplete(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 0.3)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = lambda p, total: p.emit(signal("START_SPEECH"), signal("END_SPEECH"))
        provider.on_flush = lambda p: None
        stopped, _ = stop_and_collect(ws)
    assert stopped["transcription"] == "incomplete" and "no final transcript" in stopped["reason"]


def test_final_without_speech_signals_is_incomplete(client):
    """VAD events missing: a result arrives with no START_SPEECH, so completeness cannot be confirmed."""
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = lambda p, total: None
        provider.on_flush = lambda p: p.emit(data("x-1", "transcript with no VAD events"))
        stopped, events = stop_and_collect(ws)
    assert any(e.get("text") == "transcript with no VAD events" for e in events), "result still forwarded"
    assert stopped["transcription"] == "incomplete" and "speech-detection signals" in stopped["reason"]


def test_no_provider_events_at_all_is_incomplete(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = lambda p, total: None
        provider.on_flush = lambda p: None
        stopped, _ = stop_and_collect(ws)
    assert stopped["transcription"] == "incomplete" and "no speech was detected" in stopped["reason"]


def test_slow_queue_drain_delivers_all_audio_before_flush_then_finalizes(client, monkeypatch):
    use_provider(monkeypatch, audio_delay=0.03)

    def speak(p, total):
        if total == 3200:
            p.emit(signal("START_SPEECH"))
        elif total == 6400:  # result for utterance 1 arrives while the queue is still draining after Stop
            p.emit(signal("END_SPEECH"), data("utt-1", "before the flush"))
        elif total == 9600:
            p.emit(signal("START_SPEECH"))
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = speak
        provider.on_flush = lambda p: p.emit(signal("END_SPEECH"), data("utt-2", "after the flush"))
        stopped, events = stop_and_collect(ws, frames=10)
    assert provider.log == [("audio", 3200)] * 10 + [("flush",)], "flush was not sent after all queued audio"
    assert bytes(provider.audio) == b"\x00\x00" * 16000
    assert stopped["finals_before_flush"] == 1 and stopped["finals_after_flush"] == 1
    assert stopped["transcription"] == "complete", stopped["reason"]


def test_queue_that_cannot_drain_by_the_deadline_is_incomplete_and_never_flushed(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 0.3)
    use_provider(monkeypatch, audio_delay=0.2)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        stopped, _ = stop_and_collect(ws, frames=6)
    assert stopped["transcription"] == "incomplete" and "had not reached" in stopped["reason"]
    assert not FakeProvider.instances[0].flushed
    wait_until(lambda: FakeProvider.instances[0].closed, "provider not closed")


# --- deadline and bounded shutdown ---

def test_provider_that_never_settles_is_incomplete(client, monkeypatch):
    """Every expected final arrives, but the provider keeps sending events past the deadline."""
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 0.5)
    monkeypatch.setattr(audio_ws, "FINALIZE_SETTLE_S", 0.2)

    def chatter_after_final(p):
        p.emit(signal("END_SPEECH"), data("utt-1", "the only utterance"))

        async def keep_talking():
            while not p.closed and not p.close_called:
                p.emit({"type": "events", "data": {"signal_type": "OTHER"}})  # ignored, but provider not quiet
                await asyncio.sleep(0.02)
        p.chatter = asyncio.get_running_loop().create_task(keep_talking())
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_flush = chatter_after_final
        stopped, events = stop_and_collect(ws)
    assert stopped["utterances"] == 1 and stopped["finals_after_flush"] == 1  # accounting alone looks complete
    assert stopped["transcription"] == "incomplete"
    assert "had not settled" in stopped["reason"]


def test_slow_provider_close_is_bounded_and_reported(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "PROVIDER_CLOSE_TIMEOUT_S", 0.2)
    use_provider(monkeypatch, close_delay=30)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        t0 = time.monotonic()
        stopped, _ = stop_and_collect(ws)
        elapsed = time.monotonic() - t0
    assert elapsed < 1.5, f"stop took {elapsed:.2f}s despite a bounded close"
    assert stopped["transcription"] == "complete"  # the transcript itself was fully accounted for
    assert stopped["provider_cleanup"] == "timeout"
    assert FakeProvider.instances[0].close_called
    wait_for_no_sessions()  # the session slot is released even though close never finished


def test_provider_close_error_is_reported_not_raised(client, monkeypatch):
    use_provider(monkeypatch, close_error=True)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        stopped, _ = stop_and_collect(ws)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert stopped["provider_cleanup"] == "error" and closed.value.code == 1000
    wait_for_no_sessions()


def test_normal_stop_reports_clean_provider_cleanup(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        stopped, _ = stop_and_collect(ws)
    assert stopped["transcription"] == "complete" and stopped["provider_cleanup"] == "ok"


def test_disconnect_with_hanging_provider_close_releases_the_session(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "PROVIDER_CLOSE_TIMEOUT_S", 0.2)
    use_provider(monkeypatch, close_delay=30)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 1600)
        receive_until(ws, "ack")
    wait_for_no_sessions()
    assert FakeProvider.instances[0].close_called


# --- trusted host and origin boundary ---

def counting_provider(monkeypatch):
    calls = []

    async def connect(language_code):
        calls.append(language_code)
        return FakeProvider()
    monkeypatch.setattr(audio_ws, "connect_provider", connect)
    return calls


@pytest.mark.parametrize("host,origin", [
    ("127.0.0.1:8766", "http://127.0.0.1:8766"),
    ("localhost:8766", "http://localhost:8766"),
    ("LOCALHOST:8766", "http://localhost:8766"),  # host names are case-insensitive
    ("[::1]:8766", "http://[::1]:8766"),
    ("localhost", "http://localhost:80"),  # default port on either side
    ("127.0.0.1:8766", None),  # CLI client (relay_smoke.py) sends no Origin
    ("localhost:8766", None),
])
def test_trusted_local_host_is_accepted(client, monkeypatch, host, origin):
    calls = counting_provider(monkeypatch)
    headers = {"host": host, **({"origin": origin} if origin else {})}
    with client.websocket_connect("/ws/audio", headers=headers) as ws:
        open_session(ws)
    assert calls == ["te-IN"]


@pytest.mark.parametrize("host,origin", [
    # DNS rebinding: attacker's domain resolves to 127.0.0.1, so Host and Origin match each other.
    ("evil.example:8766", "http://evil.example:8766"),
    ("evil.example:8766", None),  # untrusted Host is refused even without an Origin
    ("localhost.evil.example:8766", "http://localhost.evil.example:8766"),
    ("127.0.0.1.nip.io:8766", "http://127.0.0.1.nip.io:8766"),
    ("0.0.0.0:8766", "http://0.0.0.0:8766"),
    ("", None),  # missing Host
    # Trusted Host, foreign Origin.
    ("127.0.0.1:8766", "http://evil.example"),
    ("127.0.0.1:8766", "https://127.0.0.1.evil.example"),
    ("127.0.0.1:8766", "http://127.0.0.1:9999"),  # same host, different port
    ("127.0.0.1:8766", "http://localhost:8766"),  # different host name is a different origin
    ("127.0.0.1:8766", "null"),
    ("127.0.0.1:8766", "file://"),
    ("127.0.0.1:8766", "http://user@127.0.0.1:8766"),
    ("127.0.0.1:8766", "http://127.0.0.1:8766/path"),
    ("localhost:8766", "http://localhost"),  # Origin defaults to port 80
])
def test_untrusted_host_or_origin_is_refused_before_any_provider_session(client, monkeypatch, host, origin):
    calls = counting_provider(monkeypatch)
    headers = {"host": host, **({"origin": origin} if origin else {})}
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws/audio", headers=headers) as ws:
            ws.send_json(START)
            ws.receive_json()
    assert refused.value.code == 1008
    assert calls == [], "connect_provider was called for a refused request"
    assert audio_ws.active_sessions == 0


# --- scam-tactic detector integration ---

def speak_lines(*lines):
    """Fake provider callback: one utterance per audio frame, each with its final transcript."""
    def on_audio(p, total):
        i = total // 3200 - 1
        if 0 <= i < len(lines):
            p.emit(signal("START_SPEECH"), signal("END_SPEECH"), data(f"utt-{i}", lines[i]))
    return on_audio


def test_final_segments_reach_the_detector_and_risk_is_forwarded(client, monkeypatch):
    def respond(request):
        new = [s for s in request["segments"] if s["new"]]
        return [{"tactic": "credential_request", "status": "present", "segment_id": s["segment_id"],
                 "quote": "OTP आया है वो बताइए"} for s in new if "OTP" in s["text"]]
    use_verifier(monkeypatch, respond)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = speak_lines("मैं State Bank से बोल रहा हूँ", "अभी जो OTP आया है वो बताइए")
        provider.on_flush = lambda p: None
        stopped, events = stop_and_collect(ws, frames=2)
    risks = [e for e in events if e["type"] == "risk"]
    assert risks and risks[-1]["level"] == "red" and risks[-1]["analysis"] == "ok"
    assert risks[-1]["tactics"][0]["evidence"][0]["quote"] == "OTP आया है वो बताइए"
    assert stopped["analysis"]["status"] == "complete" and stopped["analysis"]["level"] == "red"
    requests = RecordingVerifier.instances[0].requests
    assert [s["segment_id"] for s in requests[-1]["segments"]] == ["seg1", "seg2"]  # aliases, not provider IDs
    assert risks[-1]["tactics"][0]["evidence"][0]["segment_id"] == "utt-1"  # mapped back to the real ID
    blob = json.dumps(requests)
    assert "speaker" not in blob and "language_code" not in blob and "processing_latency" not in blob
    wait_until(lambda: RecordingVerifier.instances[0].closed, "verifier not closed")


def test_detector_unavailable_is_reported_at_start_and_in_stopped(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "verifier_factory", lambda: (None, "GEMINI_API_KEY is not configured on the server"))
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        risk, _ = receive_until(ws, "risk")
        stopped, _ = stop_and_collect(ws)
    assert risk["analysis"] == "unavailable" and "GEMINI_API_KEY" in risk["error"] and risk["level"] == "none"
    assert stopped["analysis"] == {"status": "unavailable", "error": "GEMINI_API_KEY is not configured on the server"}
    assert stopped["transcription"] == "complete", "transcription completeness is reported separately"


def test_detector_failure_is_visible_and_stop_reports_analysis_incomplete(client, monkeypatch):
    use_verifier(monkeypatch, lambda request: VerifierErrorForTest("Gemini HTTP 429: quota"))
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = speak_lines("hello sir")
        provider.on_flush = lambda p: None
        stopped, events = stop_and_collect(ws)
    risk = [e for e in events if e["type"] == "risk"][-1]
    assert risk["analysis"] == "unavailable" and "429" in risk["error"]
    assert stopped["analysis"]["status"] == "incomplete" and stopped["transcription"] == "complete"


def test_stop_waits_for_analysis_of_the_flushed_segment(client, monkeypatch):
    use_verifier(monkeypatch)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        stopped, events = stop_and_collect(ws)  # default fake: the only final arrives on flush
    assert any(e["type"] == "risk" for e in events), "flushed segment was not analysed before stopped"
    assert stopped["analysis"]["status"] == "complete" and stopped["analysis"]["analysed_segments"] == 1


def test_empty_and_duplicate_finals_are_not_sent_to_the_detector(client, monkeypatch):
    use_verifier(monkeypatch)

    def on_audio(p, total):
        p.emit(signal("START_SPEECH"), data("a", "hello"), data("a", "hello"), signal("START_SPEECH"), data("b", "  "))
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = on_audio
        FakeProvider.instances[0].on_flush = lambda p: None
        stop_and_collect(ws)
    ids = [s["segment_id"] for r in RecordingVerifier.instances[0].requests for s in r["segments"]]
    assert ids == ["seg1"]  # only one segment ("a") reached the detector


def test_detector_is_closed_when_the_client_disconnects(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 1600)
        receive_until(ws, "ack")
    wait_for_no_sessions()
    wait_until(lambda: RecordingVerifier.instances[0].closed, "verifier not closed after disconnect")


def test_relay_risk_timestamps_use_the_session_clock_at_send(client, monkeypatch):
    def respond(request):
        return [{"tactic": "credential_request", "status": "present", "segment_id": s["segment_id"],
                 "quote": "OTP"} for s in request["segments"] if s["new"]]
    use_verifier(monkeypatch, respond)
    real_send_json = WebSocket.send_json
    delays = {"risk": 0}

    async def slow_send_json(self, data, mode="text"):
        if data.get("type") == "risk":
            delays["risk"] += 1
        return await real_send_json(self, data, mode)
    monkeypatch.setattr(WebSocket, "send_json", slow_send_json)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        provider = FakeProvider.instances[0]
        provider.on_audio = speak_lines("tell me the OTP")
        provider.on_flush = lambda p: None
        stopped, events = stop_and_collect(ws)
    risk = [e for e in events if e["type"] == "risk"][-1]
    assert delays["risk"] >= 1
    assert risk["emitted_at_ms"] >= risk["analysed_through_ms"] >= 0
    assert risk["first_red_at_ms"] == risk["emitted_at_ms"]
    assert stopped["analysis"]["first_red_at_ms"] == risk["first_red_at_ms"], "summary uses the same emission clock"


# --- reliability: slow analysis, malformed output, disconnects, late results, Stop, session reset ---

def red_for_new(request):
    return [{"tactic": "credential_request", "status": "present", "segment_id": s["segment_id"], "quote": "OTP"}
            for s in request["segments"] if s["new"]]


def test_analysis_slower_than_the_stop_deadline_is_reported_as_cut_off(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 0.6)
    use_verifier(monkeypatch, red_for_new, delay=5)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak_lines("tell me the OTP")
        FakeProvider.instances[0].on_flush = lambda p: None
        t0 = time.monotonic()
        stopped, events = stop_and_collect(ws)
        elapsed = time.monotonic() - t0
    a = stopped["analysis"]
    assert elapsed < 2.0, "Stop must not wait for the slow call beyond its deadline"
    assert stopped["transcription"] == "complete", "transcription completeness is independent of analysis"
    assert a["status"] == "pending" and a["cut_off_by_stop_deadline"] is True
    assert a["unanalysed_segments"] == 1 and "Stop deadline" in a["error"] and a["in_flight_for_s"] >= 0.4
    assert a["level"] == "none" and a["first_red_at_ms"] is None
    assert not [e for e in events if e["type"] == "risk"], "no result may be invented for the cut-off segment"
    wait_for_no_sessions()
    v = RecordingVerifier.instances[0]
    wait_until(lambda: v.cancelled == 1 and v.closed, "in-flight call not cancelled or verifier not closed")
    assert v.completed == 0, "the late result must never complete after the session ended"


def test_stop_during_analysis_that_finishes_in_time_reports_the_result(client, monkeypatch):
    use_verifier(monkeypatch, red_for_new, delay=0.3)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak_lines("tell me the OTP")
        FakeProvider.instances[0].on_flush = lambda p: None
        stopped, events = stop_and_collect(ws)
    risk = [e for e in events if e["type"] == "risk"]
    assert risk and risk[-1]["level"] == "red"
    assert events.index(risk[-1]) < events.index(stopped), "risk is delivered before stopped"
    a = stopped["analysis"]
    assert a["status"] == "complete" and a["cut_off_by_stop_deadline"] is False and a["in_flight_for_s"] is None
    assert a["first_red_at_ms"] == risk[-1]["emitted_at_ms"]


def test_malformed_findings_through_the_relay_fail_the_analysis_visibly(client, monkeypatch):
    def respond(request):
        return [{"tactic": "credential_request", "status": "present", "segment_id": "seg1", "quote": "not said"}]
    use_verifier(monkeypatch, respond)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak_lines("tell me the OTP")
        FakeProvider.instances[0].on_flush = lambda p: None
        stopped, events = stop_and_collect(ws)
    risk = [e for e in events if e["type"] == "risk"][-1]
    assert risk["analysis"] == "unavailable" and risk["rejected_findings"] == 1 and risk["level"] == "none"
    assert stopped["analysis"]["status"] == "incomplete" and stopped["analysis"]["unanalysed_segments"] == 1


def test_disconnect_during_analysis_cancels_the_call_and_releases_everything(client, monkeypatch):
    use_verifier(monkeypatch, red_for_new, delay=5)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak_lines("tell me the OTP")
        ws.send_bytes(b"\x00\x00" * 1600)
        receive_until(ws, "transcript")
        wait_until(lambda: RecordingVerifier.instances[0].requests, "analysis never started")
    wait_for_no_sessions()
    v = RecordingVerifier.instances[0]
    wait_until(lambda: v.cancelled == 1 and v.closed, "call not cancelled / verifier not closed after disconnect")
    wait_until(lambda: FakeProvider.instances[0].closed, "provider not closed after disconnect")
    assert v.completed == 0


def test_late_verifier_result_after_stopped_is_never_sent_or_applied(client, monkeypatch):
    """The call would finish shortly after the deadline; it is cancelled with the session, not delivered late."""
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 0.4)
    use_verifier(monkeypatch, red_for_new, delay=0.9)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak_lines("tell me the OTP")
        FakeProvider.instances[0].on_flush = lambda p: None
        stopped, _ = stop_and_collect(ws)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()  # nothing after stopped; the server closed normally
    assert stopped["analysis"]["cut_off_by_stop_deadline"] is True
    time.sleep(1.0)  # past the moment the call would have finished
    v = RecordingVerifier.instances[0]
    assert v.completed == 0 and v.cancelled == 1


def test_stop_then_start_gives_a_fresh_detector(client, monkeypatch):
    use_verifier(monkeypatch, red_for_new)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak_lines("tell me the OTP")
        FakeProvider.instances[0].on_flush = lambda p: None
        first, _ = stop_and_collect(ws)
    assert first["analysis"]["level"] == "red"
    use_verifier(monkeypatch)  # the second call says nothing dangerous
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[1].on_audio = speak_lines("hello, how are you")
        FakeProvider.instances[1].on_flush = lambda p: None
        second, events = stop_and_collect(ws)
    risk = [e for e in events if e["type"] == "risk"]
    assert risk and all(e["level"] == "none" and e["tactics"] == [] for e in risk), "state leaked across sessions"
    a = second["analysis"]
    assert a["level"] == "none" and a["calls"] == 1 and a["first_red_at_ms"] is None and a["tactics"] == []
    assert len(RecordingVerifier.instances) == 2 and RecordingVerifier.instances[0].closed
    assert [s["segment_id"] for s in RecordingVerifier.instances[1].requests[0]["segments"]] == ["seg1"]


def test_slow_analysis_mid_call_times_out_visibly_with_the_production_timeout_setting(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "DETECTOR_CALL_TIMEOUT_S", 0.2)
    use_verifier(monkeypatch, red_for_new, delay=1)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = speak_lines("tell me the OTP")
        FakeProvider.instances[0].on_flush = lambda p: None
        stopped, events = stop_and_collect(ws)
    risk = [e for e in events if e["type"] == "risk"][-1]
    assert risk["analysis"] == "unavailable" and "timed out after 0.2 s" in risk["error"]
    assert stopped["analysis"]["status"] == "incomplete"
