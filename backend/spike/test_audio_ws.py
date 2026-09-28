import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import audio_ws
from stt_provider import ProviderError

START = {"type": "start", "encoding": "pcm_s16le", "channels": 1, "sample_rate": 16000, "language_code": "te-IN"}


def data(request_id, text, duration=1.0, latency=0.3):
    return {"type": "data", "data": {"request_id": request_id, "transcript": text, "language_code": "te-IN",
                                     "metrics": {"audio_duration": duration, "processing_latency": latency}}}


def signal(kind):
    return {"type": "events", "data": {"signal_type": kind}}


class FakeProvider:
    """Scripted provider. on_audio(provider, total_bytes) and on_flush(provider) may emit events."""

    instances = []

    def __init__(self, on_audio=None, on_flush=None, block_audio=False):
        self.out = asyncio.Queue()
        self.audio = bytearray()
        self.flushed = self.closed = False
        self.on_audio, self.on_flush, self.block_audio = on_audio, on_flush, block_audio
        FakeProvider.instances.append(self)

    def emit(self, *msgs):
        for m in msgs:
            self.out.put_nowait(m)

    async def send_audio(self, pcm):
        if self.block_audio:
            await asyncio.Event().wait()  # provider never accepts audio
        self.audio.extend(pcm)
        if self.on_audio:
            self.on_audio(self, len(self.audio))

    async def flush(self):
        self.flushed = True
        if self.on_flush:
            self.on_flush(self)

    async def events(self):
        while (m := await self.out.get()) is not None:
            if isinstance(m, Exception):
                raise m
            yield m

    async def close(self):
        self.closed = True
        self.out.put_nowait(None)


def use_provider(monkeypatch, **kwargs):
    async def connect(language_code):
        return FakeProvider(**kwargs)
    monkeypatch.setattr(audio_ws, "connect_provider", connect)


@pytest.fixture(autouse=True)
def default_provider(monkeypatch):
    FakeProvider.instances.clear()
    use_provider(monkeypatch)
    monkeypatch.setattr(audio_ws, "FINALIZE_IDLE_S", 0.05)


@pytest.fixture
def client():
    return TestClient(audio_ws.app)


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
        assert ws.receive_json() == {"type": "ack", "frames": 1, "samples": 1600, "duration_s": 0.1}
        ws.send_bytes(b"\x02\x00" * 16000)
        assert ws.receive_json() == {"type": "ack", "frames": 2, "samples": 17600, "duration_s": 1.1}
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
        assert ws.receive_json()["samples"] == 16000
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
        assert ws.receive_json()["samples"] == 800
        assert audio_ws.active_sessions == 1
    wait_for_no_sessions()
    wait_until(lambda: FakeProvider.instances[0].closed, "provider not closed after client disconnect")


def test_second_session_starts_fresh(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 4000)
        assert ws.receive_json()["samples"] == 4000
    wait_for_no_sessions()
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 160)
        assert ws.receive_json() == {"type": "ack", "frames": 1, "samples": 160, "duration_s": 0.01}
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
                   data("seg-empty", "  "))
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
    assert [e["state"] for e in events if e["type"] == "speech"] == ["started", "ended"]
    assert stopped["segments"] == 1 and stopped["transcription"] == "complete" and stopped["reason"] is None


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
    assert provider.flushed and provider.closed


def test_stop_without_final_transcript_is_incomplete(client, monkeypatch):
    monkeypatch.setattr(audio_ws, "FINALIZE_TIMEOUT_S", 0.1)
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        FakeProvider.instances[0].on_audio = lambda p, total: p.emit(signal("START_SPEECH"))
        ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": "stop"})
        stopped, _ = receive_until(ws, "stopped")
    assert stopped["transcription"] == "incomplete"
    assert "no final transcript" in stopped["reason"]
    assert FakeProvider.instances[0].closed


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
    monkeypatch.setattr(audio_ws, "FINALIZE_TIMEOUT_S", 0.1)
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
    assert gaps[-1]["total_dropped_s"] == pytest.approx(0.2)  # first frame is in flight, two queued, two dropped
    assert stopped["transcription"] == "incomplete" and stopped["dropped_s"] == pytest.approx(0.2)


def test_provider_event_translation():
    assert audio_ws.provider_event(signal("START_SPEECH")) == {"type": "speech", "state": "started"}
    assert audio_ws.provider_event({"type": "events", "data": {"signal_type": "OTHER"}}) is None
    assert audio_ws.provider_event({"type": "unknown"}) is None
    with pytest.raises(ProviderError, match="quota: Rate limited"):
        audio_ws.provider_event({"type": "error", "data": {"error": "Rate limited", "code": "quota"}})
