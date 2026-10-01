# CallKavach

**A second device that listens to a doubtful speakerphone call and warns you, in Hindi, Telugu or English, when the caller uses scam tactics, showing the exact words as evidence.**

AI Build Challenge 2026 · PS-06, AI for Bharat in Indian Languages.

## The problem

"Digital arrest", KYC-block, courier and OTP scams reach people while they're on the phone. They're often elderly and often speaking a mix of Hindi or Telugu with English. The caller sounds official, creates panic, and asks for an OTP, an app install or a transfer before anyone else can intervene. Call-blocking apps judge the *number*. CallKavach listens to *what is being said*.

## What it does

Put the doubtful call on speaker, keep a phone or laptop running CallKavach next to it, and tap **Start listening**:

1. **Transcribes** the code-mixed speech (Sarvam `saaras:v3`, streaming).
2. **Checks each finished sentence** for eight scam tactics, using an LLM verifier (`gemini-2.5-flash` via AICredits). Every finding must quote the caller's exact words, or it is rejected.
3. **Applies a fixed, readable rule** to the confirmed tactics:
   - **Red** for a request for an OTP, PIN, password or remote access; a money demand with authority, threat or secrecy; or authority, threat and secrecy together.
   - **Amber** for two or more pressure tactics.
4. **Warns on screen and out loud** in the chosen language, with the quotes that triggered it. Then it offers **Call 1930** (the national cyber-crime helpline), **Tell someone you trust**, and **Report online**. Nothing is sent or reported automatically.

**Honesty rules built into the product:**
- **No "safe" verdict.** CallKavach never says a call is safe; "No warning yet" is the most it says.
- **Failures are visible.** If speech-to-text or analysis fails or falls behind, the screen says so ("analysis is unavailable", "INCOMPLETE") instead of staying quiet.
- **Evidence or nothing.** The model can't raise a warning without quoting the transcript. Any finding that fails validation rejects that whole response.
- **No numeric scores.** The app shows the backend's level and evidence, never a probability.

## Try it

| Mode | What runs |
|---|---|
| **1 · Live microphone** | Real microphone → speech-to-text → detector |
| **2 · Analyse sample audio** | One of 11 synthetic Hindi–English and Telugu–English calls (6 scams, 5 genuine look-alikes) through the same real pipeline, compared with its label afterwards |
| **3 · Recorded replay** | A session log saved from mode 1 or 2. Nothing runs; it's for presentations |
| **Evaluation report** | Shows a sanitised export of a development replay run (numbers only), served from outside the repository, if one has been published |

**Run locally:**

```bash
# Free run with no API keys: simulated transcripts, analysis shown as unavailable
STT_PROVIDER=mock LLM_PROVIDER=off uv run --no-project --with "fastapi>=0.115" --with "uvicorn>=0.30" \
  --with "websockets>=13" --with httpx uvicorn --app-dir backend/spike audio_ws:app --host 127.0.0.1 --port 8766
```

For the real pipeline, put `SARVAM_API_KEY`, `LLM_PROVIDER=aicredits`, `AICREDITS_API_KEY` and `AICREDITS_MODEL=gemini-2.5-flash` in `.env` (see `.env.example`), drop the two mock variables, and open http://127.0.0.1:8766/. To deploy, follow [DEPLOY.md](DEPLOY.md): one container, https, an access code and an hourly session cap.

## How it works

```text
phone / laptop microphone ─┐
synthetic sample WAV ──────┴─> AudioWorklet → 16 kHz PCM ─WebSocket─> FastAPI relay (/ws/audio)
                                                                        │
                                          Sarvam streaming STT <────────┤ one final per utterance
                                                                        │
                        SessionDetector: new sentences → LLM finds tactics with exact quotes
                        → strict validation → fixed rule → level only rises (none → amber → red)
                                                                        │
              browser <── risk events (level, rule, tactics, quotes, timing, cost) ──┘
              warning card · Hindi/Telugu/English clip and text · help actions · "Is it working?" panel
```

**Code map:**
- [`frontend/app/`](frontend/app/README.md): the listener app (plain ES modules).
- [`backend/spike/`](backend/spike/README.md): the relay, speech-to-text, detector and verifiers. The [detector contract](backend/spike/DETECTOR_CONTRACT.md) documents every event and field.
- `backend/evaluation/`: development data, replay runner and metrics (Navadeep).
- [`docs/`](docs): reviewed warning copy, language review, QA record.

## Evidence so far, honestly labelled

- **Tests:** offline suites cover the relay, detector, Stop and failure paths, the browser protocol, and the app lifecycle, all with mock providers and no paid calls. Commands are in the module READMEs.
- **Live smoke run (synthetic, n = 4, not an accuracy measurement):** on 1 October, with code identical to commit `06b29d6`, four macOS text-to-speech calls went through the real pipeline in Sample mode. Setup, both passes and costs are in the owner's private QA record, which is kept out of Git. Results of the second pass:
  - a Telugu–English digital-arrest call and a Hindi–English KYC/OTP call: **red**;
  - a genuine bank call that says "never share your OTP" and a genuine delivery-code call: **no warning**;
  - all four were fully analysed. Each analysis call took 4–7 s and was reported at 0.16–0.39 provider-reported cost units.
  - In the first pass, before the Stop fix, the genuine bank call was cut off at Stop and reported as INCOMPLETE, not as "no warning".
- **Development replay result (synthetic text replay, n = 10, not phone audio, not an accuracy claim):** run on 1 October at commit `f356999` with prompt tactics-v1, on the 10 development pilot calls (Hindi–English and Telugu–English, 5 scam and 5 genuine):

  | Measure | Result |
  |---|---|
  | Scam calls that reached red | 5/5 |
  | Genuine calls with a red or amber warning | 0/5 |
  | First warning (amber or red) before the scripted first dangerous request (a money transfer or OTP request) | 5/5, 6.8–22.5 s earlier; derived from the frozen run and the development ground truth |
  | Red before that request | 0/5, because red usually fires on the request itself |
  | **Calls with detector failures** | **2/10:** genuine calls with an 8 s analysis timeout, which showed "unavailable", not a warning |

  Usage: 75 analysis calls, 13.92 in provider-reported cost units, partial. The pilot's language review (10/10 accepted) was recorded after the run. The raw report stays in the owner's private QA record; only the sanitised export is published.
- **Development replay:** `backend/evaluation/run_pilot.py` measures RED recall, RED false alarms, warned-before-first-ask and amber rates on the synthetic multilingual pilot. Publish a result with `node frontend/app/export-eval-report.mjs RAW.json PUBLIC.json`. This keeps only numbers, status values and failure categories, and refuses an output path inside the repository. The server then serves that file through `CALLKAVACH_EVAL_REPORT` (see [DEPLOY.md](DEPLOY.md)), only after checking it is the sanitised form. Live results never go into Git. Until a result is published, no score is claimed.
- **Seven more synthetic calls (not yet run live):** a UPI "refund" collect request, a task-job fee, an electricity disconnection with an AnyDesk install, a customs parcel with a police threat, a loan EMI reminder, a power-cut notice and a bank complaint callback. They have sentence pauses, so warnings can arrive during the call.
- **Not yet measured:** real speakerphone audio, phone-to-phone latency, and the planned 300-call held-out test (not built in time).

## Limitations

- **One verifier.** There is a single LLM verifier, not the embedding-tagger cascade in the original plan. Latency per check is about 4–7 s, and up to 8 s before a check counts as failed.
- **Sentence-level only.** Speech-to-text returns whole sentences, so a warning can only follow the end of the sentence that contained the tactic.
- **One speaker to the app.** There is no speaker attribution: the listener's own words are transcribed too, and the prompt is asked not to count them.
- **Warning-clip gap.** While a warning clip plays (10–14 s), silence is sent instead of microphone audio, so that stretch isn't checked. The transcript marks it.
- **Limited masking.** Only digit runs of 4 or more are masked before analysis; spoken-out numbers are not.
- **Synthetic audio only.** Every sample is synthetic. No real victims' calls were used.

## Credits and licences

- **Speech and analysis:** speech-to-text by [Sarvam AI](https://www.sarvam.ai/); analysis by Google Gemini through [AICredits](https://aicredits.in/).
- **Warning clips:** offline [Piper](https://github.com/rhasspy/piper) voices (see [docs/warning-copy.md](docs/warning-copy.md)).
  - Hindi `hi_IN-priyamvada-medium`: CC BY-NC-SA 4.0.
  - Telugu `te_IN-padmavathi-medium`: CC BY 4.0.
  - English `en_US-amy-medium`: see its model card.
  - Wording was reviewed by a fluent Hindi/Telugu team member.
- **Sample calls:** macOS `say` text-to-speech of lines written by the team, for demonstration only.

## Team and process

Cyril (Chaitanya Pudota) owns integration, the frontend and the final submission. Navadeep built the evaluation module, and Harshit the warning copy, clips, language review and QA. `main` is protected: every change arrives through a reviewed pull request ([CONTRIBUTING.md](CONTRIBUTING.md)). The original [build plan](CallKavach-Build-Plan.md) is kept as written on 29 September; this README describes what was actually built.

Keep API keys in `.env` or the host's secret settings, never in Git.
