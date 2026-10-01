# CallKavach listener app

The user-facing page, served by the relay at `/`. Plain HTML and ES modules, no build step. It reuses the capture spike's resampler, frame sender and AudioWorklet from `../spike/`.

```
uv run --no-project --with "fastapi>=0.115" --with "uvicorn>=0.30" --with "websockets>=13" --with httpx uvicorn --app-dir backend/spike audio_ws:app --host 127.0.0.1 --port 8766
```

Open http://127.0.0.1:8766/. For a local run with no paid calls, put `STT_PROVIDER=mock LLM_PROVIDER=off` in front: transcription is simulated and analysis shows as unavailable.

## Modes

1. **Live microphone** (`#live`). It captures the speakerphone through this device's microphone and streams 16 kHz PCM to this page's own `/ws/audio`.
2. **Analyse sample audio** (`#sample`). It sends a synthetic WAV from `/samples/` through the same real pipeline, paced in real time. Four offline-generated synthetic WAVs are included in the repository so this mode works in a clean checkout. To regenerate them on macOS, run `bash backend/spike/make_samples.sh`. The scam or genuine label is compared only when the run is complete.
3. **Recorded replay** (`#replay`). It plays back a session log that you saved from Live or Sample mode with **Save session log**. The log is a local file (`callkavach.session_log.v1`) containing the relay's own messages, transcripts included. It is never uploaded and never committed. Nothing runs during replay.
4. **Evaluation report** (`#eval`). It reads `/eval/report.json`, which the relay serves from `CALLKAVACH_EVAL_REPORT` or `CALLKAVACH_EVAL_REPORT_JSON` (`backend/spike/public_eval.py`). It never comes from a file in the repository; `frontend/app/eval/` is gitignored, and nothing under `/eval/` is served from it. The file is a `callkavach.public_eval.v1` export made by `node frontend/app/export-eval-report.mjs RAW.json PUBLIC.json`, which refuses an output path inside the repository.
   - **What the export keeps:** a whitelist from a `backend/evaluation/run_pilot.py` result: aggregate metrics, per-call timing and status, failure *categories*, and the reproducibility manifest.
   - **What it drops:** risk events, evidence quotes, detector summaries, verifier metadata and any free text.
   - **Raw reports:** the raw runner report holds transcript-derived text. The server refuses to serve it, and `eval-report.js` refuses to display it.
   - **No report:** if the file is missing, nothing is shown. No example numbers are shipped.

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

Expected at `/assets/warnings/{amber|red}-{hi|te|en}.mp3` (or `.wav`), from the repository's `assets/` folder. The sound test plays the amber clip in the chosen language. If a clip is missing, the page says spoken warnings are unavailable and shows the warning on screen only.

## Tests

```
node --test frontend/app/session-core.test.js frontend/app/eval-report.test.js
```

`session-core.js` holds the protocol, reducer and Stop classification, with no DOM. The tests also check that `app.js` sends no text message other than `start` and `stop`.

Browser lifecycle tests: run the relay with `STT_PROVIDER=mock LLM_PROVIDER=off` (no paid calls), open http://127.0.0.1:8766/lifecycle.test.html, and click **Run lifecycle tests**. This browser gesture lets the synthetic microphone's AudioContext run. The app runs in an iframe with that synthetic microphone. The title reads `ALL PASSED` when:
- Stop tapped right after `ready`, while the AudioWorklet is still loading, still sends `stop` and gets the server's `stopped` reply;
- a worklet that fails after Stop doesn't turn the result into a microphone error;
- a worklet failure while listening is reported and releases the microphone;
- Start → Stop → Start streams audio, and each Stop is confirmed.

## Not done here

- **Phone access:** getUserMedia needs https. A phone reaches the app only after deployment with `CALLKAVACH_PUBLIC_HOSTS` set (see `DEPLOY.md`).
- **Warning wording:** the reviewed spoken-warning sentence from `docs/warning-copy.md` is shown on the warning card in the session's language (a test keeps the two identical). The rest of the interface is English.

## Phone behaviour

- **Microphone capture:** the capture AudioContext is created inside the Start tap, which iOS Safari requires.
- **Screen:** a screen wake lock is held while listening.
- **Stalled microphone:** if no audio arrives for 4 s (screen locked, app in the background, another app took the microphone), the session fails visibly as "Microphone stopped" instead of showing "Listening".
- **Muting during warnings:** the microphone is muted only while a clip is really playing. A clip that never reports its end is cut off after its length plus 1 s. Muted time is reported at Stop as not checked.
- **15-minute limit:** sessions stop on their own at 14:30 of audio, before the relay's 15-minute limit.
