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


@pytest.fixture(autouse=True)
def default_provider(monkeypatch):
    FakeProvider.instances.clear()
    use_provider(monkeypatch)
    monkeypatch.setattr(audio_ws, "FINALIZE_SETTLE_S", 0.05)
    monkeypatch.setattr(audio_ws, "FINALIZE_DEADLINE_S", 2.0)


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
