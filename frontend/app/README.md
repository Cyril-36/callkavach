# CallKavach listener app

The user-facing page, served by the relay at `/`. Plain HTML and ES modules, no build step. It reuses the capture spike's resampler, frame sender and AudioWorklet from `../spike/`.

```
uv run --no-project --with "fastapi>=0.115" --with "uvicorn>=0.30" --with "websockets>=13" --with httpx uvicorn --app-dir backend/spike audio_ws:app --host 127.0.0.1 --port 8766
```

Open http://127.0.0.1:8766/. For a local run with no paid calls, put `STT_PROVIDER=mock LLM_PROVIDER=off` in front: transcription is simulated and analysis shows as unavailable.

## Modes

1. **Live microphone** (`#live`). It captures the speakerphone through this device's microphone and streams 16 kHz PCM to this page's own `/ws/audio`.
2. **Analyse sample audio** (`#sample`). It sends a synthetic WAV from `/samples/` through the same real pipeline, paced in real time. Generate the WAVs with `bash backend/spike/make_samples.sh`; they are not in Git, so a server without them shows "Couldn't load the sample audio". The scam or genuine label is compared only when the run is complete.
3. **Recorded replay** (`#replay`). It plays back a session log that you saved from Live or Sample mode with **Save session log**. The log is a local file (`callkavach.session_log.v1`) containing the relay's own messages, transcripts included. It is never uploaded and never committed. Nothing runs during replay.
4. **Evaluation report** (`#eval`). It reads the static file `eval/report.json` next to this page and shows nothing if the file is missing. No example numbers are shipped.

## Protocol (backend/spike/DETECTOR_CONTRACT.md)

- **Sent:** `start` (with `language_code` `hi-IN`, `te-IN` or `en-IN`), binary audio frames, and `stop`. Nothing else: the relay ends the session on any other text message.
- **Warning playback:** while a warning clip plays, silence frames are sent instead of microphone audio, so the clip isn't transcribed. The transcript marks the span.
- **Stop:**
  1. The microphone is released at once.
  2. Silence is streamed: at least 1.5 s, so the last sentence ends through the transcriber's own end-of-speech detection, then up to 12 s more while a sentence is still open or the last segments are still being checked. Microphone audio is never sent after Stop. The relay's 6 s deadline is unchanged.
  3. `stop` is sent, and the app waits up to 8 s for `stopped`. The relay's deadline is 6 s, plus a 1 s provider close.
- **When a session counts as fully checked:** only when `stopped.transcription` is `complete`, `stopped.analysis.status` is `complete`, and no audio was dropped. Anything else gets an "INCOMPLETE" headline with the reasons: incomplete transcription, a Stop-deadline cut-off (a cancelled call or queued segments), incomplete or unavailable analysis, dropped audio, or no reply.
- **Failed analysis:** `risk.analysis: "unavailable"` is shown as a failure ("Listening, but analysis is unavailable"), never as "No warning yet".
- **Levels:** only the backend sets them. The page maps tactic names to wording and never computes a score.

## Warning clips

Expected at `/assets/warnings/{amber|red|test}-{hi|te|en}.mp3` (or `.wav`), from the repository's `assets/` folder. If a clip is missing, the page says spoken warnings are unavailable and shows the warning on screen only.

## Tests

```
node --test frontend/app/session-core.test.js
```

`session-core.js` holds the protocol, reducer and Stop classification, with no DOM. The tests also check that `app.js` sends no text message other than `start` and `stop`.

Browser lifecycle tests: run the relay with `STT_PROVIDER=mock LLM_PROVIDER=off` (no paid calls) and open http://127.0.0.1:8766/lifecycle.test.html. The app runs in an iframe with a synthetic microphone. The title reads `ALL PASSED` when:
- Stop tapped right after `ready`, while the AudioWorklet is still loading, still sends `stop` and gets the server's `stopped` reply;
- a worklet that fails after Stop doesn't turn the result into a microphone error;
- a worklet failure while listening is reported and releases the microphone;
- Start → Stop → Start streams audio, and each Stop is confirmed.

## Not done here

- **Phone access:** getUserMedia needs https, and the relay only trusts `localhost`, `127.0.0.1` and `[::1]` as Host. A phone can reach the app only after deployment with a configured host.
- **Warning wording:** copy in Hindi and Telugu is pending `docs/warning-copy.md`, and the on-screen text is English.
