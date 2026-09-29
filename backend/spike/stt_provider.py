"""Speech-to-text providers for the audio spike.

A provider stream has: send_audio(pcm_bytes), flush(), events() (async iterator of
provider messages in Sarvam's shape), close(). Protocol taken from the sarvamai SDK
(0.1.34): wss://api.sarvam.ai/speech-to-text/ws, query parameters below, audio sent as
{"audio": {"data": <base64>, "sample_rate": 16000, "encoding": "audio/wav"}}, and
{"type": "flush"} to force finalization. Replies are {"type": "data"|"events"|"error", "data": {...}}.
Sarvam's streaming API returns final transcripts per detected utterance, not partials.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import websockets

SARVAM_URL = "wss://api.sarvam.ai/speech-to-text/ws"
SARVAM_MODEL = "saaras:v3"


class ProviderError(Exception):
    pass


def _api_key():
    if os.environ.get("SARVAM_API_KEY"):
        return os.environ["SARVAM_API_KEY"]
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "SARVAM_API_KEY" and value.strip():
                return value.strip()
    return None


class SarvamStream:
    def __init__(self, ws):
        self.ws = ws

    async def send_audio(self, pcm: bytes) -> None:
        audio = {"data": base64.b64encode(pcm).decode(), "sample_rate": 16000, "encoding": "audio/wav"}
        await self.ws.send(json.dumps({"audio": audio}))

    async def flush(self) -> None:
        await self.ws.send(json.dumps({"type": "flush"}))

    async def events(self):
        try:
            async for raw in self.ws:
                yield json.loads(raw)
        except websockets.ConnectionClosedError as e:
            raise ProviderError(f"Sarvam connection closed unexpectedly (code {e.code})") from e

    async def close(self) -> None:
        await self.ws.close()


async def connect_sarvam(language_code: str) -> SarvamStream:
    key = _api_key()
    if not key:
        raise ProviderError("SARVAM_API_KEY is not configured on the server")
    params = {
        "language-code": language_code,
        "model": SARVAM_MODEL,
        "mode": "codemix",
        "sample_rate": "16000",
        "input_audio_codec": "pcm_s16le",
        "vad_signals": "true",
        "flush_signal": "true",
    }
    try:
        ws = await websockets.connect(f"{SARVAM_URL}?{urlencode(params)}",
                                      additional_headers={"Api-Subscription-Key": key},
                                      open_timeout=10, max_size=2**20)
    except Exception as e:  # handshake rejection, DNS, timeout
        raise ProviderError(f"could not connect to Sarvam ({type(e).__name__}: {e})") from e
    return SarvamStream(ws)


class MockStream:
    """Local stand-in for browser tests: one final transcript per second of audio, and on flush."""

    def __init__(self):
        self.out = asyncio.Queue()
        self.pending_bytes = 0
        self.count = 0

    def _emit_transcript(self):
        self.count += 1
        self.out.put_nowait({"type": "data", "data": {
            "request_id": f"mock-{self.count}", "transcript": f"mock segment {self.count}",
            "language_code": "en-IN", "metrics": {"audio_duration": self.pending_bytes / 32000, "processing_latency": 0.0}}})
        self.pending_bytes = 0

    async def send_audio(self, pcm: bytes) -> None:
        if self.pending_bytes == 0:
            self.out.put_nowait({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        self.pending_bytes += len(pcm)
        if self.pending_bytes >= 32000:
            self._emit_transcript()

    async def flush(self) -> None:
        if self.pending_bytes:
            self._emit_transcript()

    async def events(self):
        while (msg := await self.out.get()) is not None:
            yield msg

    async def close(self) -> None:
        self.out.put_nowait(None)


async def connect_mock(language_code: str) -> MockStream:
    return MockStream()


def default_connector():
    return connect_mock if os.environ.get("STT_PROVIDER") == "mock" else connect_sarvam
