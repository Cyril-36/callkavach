# Audio spike: Sarvam STT smoke test

Minimal check that Sarvam speech-to-text returns usable transcripts for code-mixed Telugu-English and Hindi-English audio. No WebSocket, frontend or detection yet.

Endpoint used: `POST https://api.sarvam.ai/speech-to-text`, header `api-subscription-key`, form fields `file`, `model` (`saaras:v3` default, `saaras:v4`), `mode` (`codemix`), `language_code` (`te-IN`, `hi-IN`). Streaming (`/speech-to-text/ws`, 16 kHz PCM or WAV, base64) is the later target; REST is used here to test accuracy first.

## Run

Requires macOS (`say` with Geeta/Lekha voices), `ffmpeg`, `uv`, and `SARVAM_API_KEY` in the environment or the repo's `.env`.

```bash
bash backend/spike/make_samples.sh
uv run backend/spike/stt_smoke.py backend/spike/samples/te_en_digital_arrest.wav:te-IN backend/spike/samples/hi_en_kyc.wav:hi-IN
```

Add `--model saaras:v4` to compare models. Exit code: 0 all succeeded, 1 an API error, 2 no key.

## WebSocket audio receiver

`audio_ws.py` accepts `/ws/audio`: a JSON start message declaring `pcm_s16le`, mono, 16 kHz, then binary frames (non-empty, whole 16-bit samples, at most 1 s each). Each frame is acknowledged with cumulative samples and duration; `{"type": "stop"}` ends the session. Limits: 15 min of audio per session, 4 concurrent sessions, 10 s to send the start message. Audio is counted and discarded, never stored. It also serves `frontend/spike/` at `/`, so the browser capture page streams to it from the same origin (see `frontend/spike/README.md`). Not yet connected to Sarvam.

```bash
uv run --no-project --with "fastapi>=0.115" --with httpx --with pytest pytest -q backend/spike/test_audio_ws.py
```

Samples are synthetic TTS (clean studio audio, one speaker). They do not represent speakerphone audio picked up by a second device; results here are not an accuracy claim.
