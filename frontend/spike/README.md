# Microphone capture spike

Browser microphone → AudioWorklet (mono Float32) → streaming resampler (Blackman-windowed sinc low-pass, then linear interpolation) → 16 kHz Int16 → 100 ms little-endian frames over a WebSocket to `/ws/audio` (`backend/spike/audio_ws.py`). The page shows what the browser captured and sent next to what the server acknowledged. If the socket's send buffer passes 64 KB (about 2 s of audio), frames are dropped and counted rather than queued. Nothing is stored; the server only counts samples.

```bash
node --test frontend/spike/resample.test.js frontend/spike/pcm-sender.test.js
```

The FastAPI spike serves this page and the socket from one origin (microphone access needs localhost or HTTPS):

```bash
uv run --no-project --with "fastapi>=0.115" --with "uvicorn>=0.30" --with websockets uvicorn --app-dir backend/spike audio_ws:app --host 127.0.0.1 --port 8766
```

Open http://127.0.0.1:8766/. Add `?ws=ws://host:port/ws/audio` to use a different receiver. `websockets` is required: without it uvicorn answers the upgrade with 404.

Lifecycle tests (browser only, synthetic microphone, real socket): with that server running, open http://127.0.0.1:8766/lifecycle.test.html. The title reads `ALL PASSED` when Start → Stop → Start streams matching sample counts, and a forced `source.connect` failure, a rejected `ctx.close()`, a server error mid-session and an unreachable server all leave the microphone released and Start usable.
