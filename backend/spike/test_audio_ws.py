import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import audio_ws

START = {"type": "start", "encoding": "pcm_s16le", "channels": 1, "sample_rate": 16000}


@pytest.fixture
def client():
    return TestClient(audio_ws.app)


def open_session(ws):
    ws.send_json(START)
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    return ready


def expect_error(ws, code, close_code):
    msg = ws.receive_json()
    assert msg == {"type": "error", "code": code, "message": msg["message"]}
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == close_code


def wait_for_no_sessions():
    for _ in range(100):
        if audio_ws.active_sessions == 0:
            return
        time.sleep(0.01)
    pytest.fail(f"{audio_ws.active_sessions} session(s) still active")


def test_valid_frames_are_acknowledged_cumulatively(client):
    with client.websocket_connect("/ws/audio") as ws:
        ready = open_session(ws)
        assert ready["max_frame_bytes"] == 32000
        ws.send_bytes(b"\x00\x00" * 1600)  # 0.1 s
        assert ws.receive_json() == {"type": "ack", "frames": 1, "samples": 1600, "duration_s": 0.1}
        ws.send_bytes(b"\x01\x00" * 16000)  # 1 s, the maximum frame
        assert ws.receive_json() == {"type": "ack", "frames": 2, "samples": 17600, "duration_s": 1.1}
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == {"type": "stopped", "frames": 2, "samples": 17600, "duration_s": 1.1}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1000
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


def test_client_disconnect_mid_session_is_cleaned_up(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00" * 800)
        assert ws.receive_json()["samples"] == 800
        assert audio_ws.active_sessions == 1
    # Leaving the block closes the socket without a stop message.
    wait_for_no_sessions()


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
