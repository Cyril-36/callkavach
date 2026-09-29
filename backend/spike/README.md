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

## WebSocket audio receiver and Sarvam relay

`audio_ws.py` accepts `/ws/audio`: a JSON start message declaring `pcm_s16le`, mono, 16 kHz and `language_code` (`te-IN`, `hi-IN` or `en-IN`), then binary frames (non-empty, whole 16-bit samples, at most 1 s each). The server opens a Sarvam realtime session (`stt_provider.py`: `saaras:v3`, `codemix`, raw PCM, VAD events, flush) before replying `ready`, acknowledges every frame, and relays audio through a queue capped at 5 s; frames beyond that are dropped and reported as `gap` events. Sarvam's `START_SPEECH`/`END_SPEECH` become `speech` events and each final transcript is forwarded once. Sarvam's streaming API sends final transcripts per utterance, not partials. Stop first delivers every accepted queued frame, then sends Sarvam's flush, then waits (one 6 s deadline in total, inside the browser's 8 s) until every `START_SPEECH` has its final result and the provider has been quiet for 1 s. Sarvam sends nothing in reply to a flush when no utterance is open, so completion is judged by utterance accounting, not by waiting for a flush reply. `stopped` reports `complete` only if all audio reached Sarvam, nothing was dropped, and every started utterance has a final result; missing results, missing or inconsistent speech-detection signals, no detected speech, undelivered or dropped audio all report `incomplete` with the reasons. If the provider is still sending events when the deadline passes, that is also `incomplete`. Closing Sarvam is bounded to 1 s (6 s + 1 s stays inside the browser's 8 s) and reported separately as `provider_cleanup: ok | timeout | error`; a close that times out keeps running in the background and never holds the session open. Provider failures close the browser socket with `provider_error` (1011). `SARVAM_API_KEY` stays on the server (environment or repo `.env`). This app does not save recordings or transcripts; audio is sent to Sarvam for transcription, and Sarvam's own data handling is governed by its terms.

**Local-spike security.** `/ws/audio` accepts only a `Host` of `localhost`, `127.0.0.1` or `[::1]` (any port), which stops DNS rebinding, where an attacker's domain resolves to 127.0.0.1 and sends a matching `Host` and `Origin` of its own. A browser `Origin` must then name exactly that host and port (default ports 80/443 apply). Anything else is refused with HTTP 403 before any Sarvam session opens. Clients that send no `Origin`, such as `relay_smoke.py`, are allowed on a trusted `Host`. Open the page and run the CLI through the same host name you use (`127.0.0.1` and `localhost` are different origins). This only stops other websites from using a visitor's browser to reach the relay; it is **not authentication**, because any non-browser client can set or omit the header. A public deployment additionally needs authentication and rate limits before it can be exposed. Limits: 15 min of audio per session, 4 concurrent sessions, 10 s to send the start message.

```bash
uv run --no-project --with "fastapi>=0.115" --with httpx --with pytest --with pytest-asyncio --with websockets pytest -q backend/spike/test_audio_ws.py
```

Tests use a scripted fake provider; `STT_PROVIDER=mock` runs the server with a local stand-in (one "mock segment" per second of audio) for browser tests without Sarvam calls.

Real relay check: with the server running (see `frontend/spike/README.md`), stream a WAV in real time and print every event with its arrival time:

```bash
uv run backend/spike/relay_smoke.py backend/spike/samples/te_en_digital_arrest.wav te-IN
```

Samples are synthetic TTS (clean studio audio, one speaker). They do not represent speakerphone audio picked up by a second device; results here are not an accuracy claim.

## Incremental scam-tactic detector

`detector.py` holds the contract and the deterministic risk policy. `verifier_config.py` chooses **exactly one** provider (no fallback): `aicredits_verifier.py` (AICredits gateway, OpenAI-compatible, **primary and default**) or `gemini_verifier.py` (direct Google Gemini, selected explicitly). The relay feeds each **finalized, non-empty, first-seen** transcript segment to a per-session `SessionDetector`, in arrival order, and forwards its `risk` events to the browser. The page ignores these for now; the dashboard and spoken warnings are later work.

- **Input contract.** Only `segment_id`, `text` and the server's receive time. No speaker labels (live STT has none), family IDs, scam/genuine labels, first-ask times or future segments. Evaluation data and ground truth are not used as prompt examples.
- **Short aliases.** The model sees segments as `seg1`, `seg2`, … and the detector maps findings back to real segment IDs. In a live run the model mis-copied Sarvam's long request IDs and every finding was rejected.
- **No spelling gate.** Every finalized segment is analysed, because Sarvam transliterates or mishears acronyms (OTP / ओटीपी, KYC → कार्ड/कैट, Cyber → "Cibir"). The prompt tells the model to judge meaning, not spelling.
- **Strict validation.** A reply that is not a list of findings is a failed analysis. Each finding must have exactly `tactic`, `status` and `segment_id`, `quote`, with an optional `reason`; all strings; a known tactic and status (`present | negated | benign`); an alias from this request; and a non-empty quote of at most 300 characters that occurs in that segment. Negated and benign findings are validated too, but only `present` ones are evidence. If any finding in a response is rejected, the whole response is a failed analysis (`analysis: "unavailable"`). Nothing from it is applied, not even its valid findings; the current warning is kept; and its segments stay unanalysed and are re-offered as new on the next call while they are still in the window.
- **Risk is computed in code, not by the model.** `red` for a credential or remote-access request, a money request plus authority, threat or secrecy, or authority + threat + secrecy together. `amber` for two or more pressure tactics. Otherwise `none`, which means "no warning yet", never "safe". Warnings are never cleared during a session.
- **Real emission timestamps.** The relay builds each `risk` event after acquiring its WebSocket send lock, immediately before the write, and stamps `emitted_at_ms` on its session clock. `first_warning_at_ms`, `first_red_at_ms` and the `stopped.analysis` summary use the same emission times. `analysed_through_ms` is the receive time of the newest analysed segment. These are the alert times evaluation should use, not segment or model times. See `DETECTOR_CONTRACT.md`.
- **Bounds.** One call in flight; segments that arrive meanwhile are coalesced. At least 1 s between calls, an 8 s timeout per call, at most 60 calls per session, and at most 50 queued segments. Context is the last 12 segments within 4,000 characters, plus up to 3 retained quotes per confirmed tactic, so early clues survive. Runs of four or more digits are masked as `[NUMBER]` before anything leaves the server. Spelled-out numbers and names are not masked.
- **Failures are visible.** A timeout, HTTP error, blocked or truncated reply, model mismatch, malformed reply, rejected finding or exhausted budget emits `analysis: "unavailable"` with the reason and keeps the current level. Stop waits, within the same 6 s deadline, for analysis of the final segments. `stopped.analysis` reports `complete | incomplete | pending | unavailable` separately from transcription completeness. If the deadline ends the session while a call is in flight, `stopped.analysis` has `status: "pending"`, `cut_off_by_stop_deadline: true`, `in_flight_for_s` and an explicit error; the in-flight call is cancelled and its result is never delivered or applied.
- **Timeouts.** The production per-call timeout is `DETECTOR_CALL_TIMEOUT_S = 8.0` in `audio_ws.py`, and the provider HTTP timeout is also 8 s.

### Configuration (server-side only, environment or `.env`)

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER` | `aicredits` (default), `gemini`, or `off` (no analysis, reported as unavailable: use for tests that must not make paid calls) |
| `AICREDITS_API_KEY`, `AICREDITS_MODEL` | AICredits gateway. The model is currently `gemini-2.5-flash`. `AICREDITS_BASE_URL` defaults to `https://api.aicredits.in` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Direct Google Gemini, only when `LLM_PROVIDER=gemini` |

There are no default models. If the gateway answers with a different model from the one configured, the reply is rejected; nothing is substituted. AICredits documents only `response_format: {"type": "json_object"}` (no JSON schema), so the output format is enforced by the prompt and the strict local validation.

**Privacy.** With AICredits, the redacted recent transcript text passes through the AICredits gateway to Google. According to AICredits, request and response content is stored for 30 days by default, subject to the account's retention settings, so the period can differ per account: check this account's settings rather than assuming 30 days. Content is routed to model providers outside India. Use synthetic or consented audio only.

Live check with the configured provider (synthetic conversations only; makes billed calls). Its default `--timeout 30` applies to both the detector and the provider's HTTP client, so it measures latency; it is **not** a measure of reliability under the production 8 s timeout. Pass `--timeout 8` for that:

```bash
uv run --no-project --with httpx python backend/spike/detector_smoke.py
```

## End-to-end harness and evaluation replay

- **`e2e_harness.py`** runs synthetic WAVs (`make_samples.sh`) through the real relay, started in-process: real Sarvam, then the configured detector. It writes a `callkavach.e2e_report.v1` JSON report and uses `relay_client.py`, the same client `relay_smoke.py` uses. `--mode production` is the relay as configured (8 s analysis timeout). `--mode measurement` raises the analysis and HTTP timeouts to 30 s for latency observation only. `--stop pause|abrupt|both` controls whether Stop follows 1.5 s of silence or comes right after the speech. Every run makes billed calls.
- **`replay.py`** replays one call's `detector_view` text through the real detector for the offline evaluation runner (`callkavach.detector_replay.v1`).
- **`DETECTOR_CONTRACT.md`** documents the event, summary and report fields and their clocks.

```bash
uv run --no-project --with "fastapi>=0.115" --with "uvicorn>=0.30" --with "websockets>=13" --with httpx \
    python backend/spike/e2e_harness.py --mode production --stop both --json e2e_report.json
```

Automated tests (no network, no paid calls):

```bash
uv run --no-project --with "fastapi>=0.115" --with "uvicorn>=0.30" --with httpx --with pytest --with pytest-asyncio --with websockets pytest -q backend/spike/
```
