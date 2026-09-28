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

Samples are synthetic TTS (clean studio audio, one speaker). They do not represent speakerphone audio picked up by a second device; results here are not an accuracy claim.
