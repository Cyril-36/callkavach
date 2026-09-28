# CallKavach: revised build plan

Confirmed 29 September 2026. This is the implementation plan; no application has been implemented or tested yet.

The acceptance screenshots say the final project must use the same submitted problem statement, with a deadline of **1 October 2026, 11:59 PM IST**. Aim to submit at 8 PM. Check the official group for the actual submission fields and video requirements. The pasted “52 hours” is a historical estimate, not a fresh countdown.

The accepted deck is PS-06, AI for Bharat in Indian Languages. Its actual interaction is a doubtful call on speaker, with CallKavach listening on a **second device**. Preserve that scope. The ownership model proposed here is Chaitanya plus Codex handling implementation and integration, with Harshit and Navadeep supplying bounded content and testing work. These assignments are proposed, not sent.

## Verdict and required corrections

The direction is sound for a hackathon prototype. Keep all five promised features: live listener, tactic evidence, spoken warning, user-initiated help actions, and evaluation dashboard. The following changes are required before treating the pasted plan as implementation-ready.

1. **Separate replay from inference.** A saved event timeline is a UI fixture. It does not test STT or the detector. Provide visibly labelled Live microphone, Analyse sample audio, and Recorded replay modes. Sample analysis sends audio through the actual pipeline. Recorded replay shows previously saved results and is a presentation fallback. Hand-authored fixtures must say illustrative.
2. **Prove the audio transport first.** Do not assume successive MediaRecorder blobs are independent audio files. Use a tested PCM stream at the provider's required rate; a fallback can package that same PCM into valid short WAV windows with overlap and transcript deduplication. Check real Telugu-English and Hindi-English speech. API support is not evidence of adequate accuracy.
3. **Treat tactics as hypotheses with evidence.** An embedding match is a candidate, not proof. A quote matching the transcript proves provenance, not that its interpretation is right. The verifier must distinguish requests from negations, quotations, victim responses, and legitimate support. Use “claimed authority” rather than treating every police/bank introduction as proven impersonation. The three separate red paths are the digital-arrest combination, a verified credential/remote-access request, and a coercive money request.
4. **Preserve the evaluation promise accurately.** Slide 8 describes a planned 300-call test set: 150 scams and 150 genuine look-alikes. Generating 300 total and taking a dev split leaves fewer than 300 test calls. Either keep separate dev data plus 300 held-out tests, or disclose the smaller achieved test size. Never reuse test families as exemplars.
5. **Define failures and privacy before implementation.** STT/LLM failure must show analysis unavailable or verification pending, never a reassuring safe state. Avoid automatically saving every live transcript to JSONL because transcripts can contain sensitive details, even though text events are not call audio. Keep live audio and text in bounded memory, discard on stop/expiry, and restrict persistent replay fixtures and caches to synthetic or explicitly consented evaluation data.
6. **Use measured outputs.** The slide's risk values, 39-second alert, and 2m33s lead are illustrative. Do not hardcode them as live results or label an uncalibrated score a scam probability.

## Product and architecture

Use React + Vite + Tailwind for the frontend, FastAPI for the backend, a tested Sarvam STT endpoint, a multilingual embedding tagger, Gemini structured verification, and pre-generated Bulbul warning clips. Pin the model IDs, dependency versions, prompt version and rule configuration after the integration spike. Do not assume the newest advertised model is available to the account.

```text
Second-device microphone / sample audio
  -> PCM audio -> FastAPI -> Sarvam STT
  -> finalized transcript segments
  -> embedding candidates + conservative credential-request triggers
  -> bounded-context Gemini verification when new evidence appears
  -> deterministic state reducer
  -> transcript / tactic / status / warning events
  -> listener screen + desktop dashboard
```

Replay feeds saved events directly to the UI. Text evaluation bypasses STT but uses the same detector. Audio evaluation includes STT; speaker playback tests additionally exercise microphone capture and room acoustics.

No accounts, database, native mobile app, automatic call blocking, autonomous reporting, fine-tuning, or agent framework are needed for this deadline. One backend process and a bounded number of concurrent sessions are sufficient for the prototype. Protect the public endpoint with session limits, duration limits, payload limits and a global API budget; keep keys server-side.

Choose one backend host during the first deployment spike. A FastAPI host that also serves the built frontend reduces integration work; separate static frontend hosting is fine if already familiar. Verify WebSockets, memory use, HTTPS and available credits before committing. Render Free is a possible option, but its documented idle spin-down and ephemeral filesystem require visible reconnect/warm-up handling. Do not assume any hosting/API option is free for this account. Capture raw browser audio, measure the actual sample rate, then resample to the rate required by the selected Sarvam endpoint. Do not merely label 48 kHz input as 16 kHz.

## Shared data and state contract

Agree this before building the UI against fixtures:

- Session: ID, mode, warning language, consent state, start time, lifecycle, provider health.
- Transcript: segment ID, audio start/end timestamps, text, final/interim flag. Score finalized segments only; display partials without committing risk. Do not pretend speaker attribution is reliable if it has not been implemented and tested.
- Evidence: tactic ID, source segment and span, context, candidate/confirmed/rejected state, verifier version.
- Event: schema version, session ID, sequence number, type, audio timestamp, emission timestamp, payload.
- Evaluation: call ID, family ID, speaker ID when available, language, ground truth, first-ask timestamp, actual alert-emission timestamp and errors. Freeze one configuration file and record its Git commit/tag plus cache usage in the run manifest.

Use an incremental interface such as `process_segment(state, segment) -> state, events`. A `score_call` wrapper feeds only the prefix available at each point. The keyword baseline shares input timing and metric code, but has its own detection logic. It must not call the main detector and thereby inherit its predictions.

Process finalized segments in order within a session; prevent concurrent verifier responses from overwriting newer state. Deduplicate overlapping audio windows and repeated evidence. Display interim text without committing risk. If the selected STT endpoint revises segments it called final, record this during the spike and decide whether support is needed. Closing a session cancels outstanding calls; a new session starts clean.

## Initial warning policy to validate on dev data

These are proposed heuristics, not validated safety rules.

- **No warning yet:** insufficient evidence; never labelled “safe”.
- **Amber:** at least two distinct suspicious tactic categories in context. Candidate-only concern must be labelled unverified. Start verification when a new combination appears.
- **Red, before the ask:** confirmed combination of claimed authority, coercive threat/fabricated-crime allegation, and secrecy/isolation. A generic count of three unrelated tags is too loose.
- **Red, at a dangerous request:** confirmed request to reveal banking credentials/PIN/OTP or install/give remote access; or a confirmed money-transfer request combined with coercive authority, threats or secrecy. Display caution and evidence, not a claim of legal certainty.
- **Negation and benign context:** “never share your OTP”, quoted fraud education, a delivery-code exchange and legitimate support are dedicated counterexamples. Aadhaar/PAN mentions alone do not justify red.
- **Verification timeout/error:** retain already supported warnings, visibly mark new evidence pending/unavailable, and allow a bounded retry. Do not promote unverified evidence to confirmed red or silently clear a warning.

Each tactic contributes once, but can have several supporting spans. Preserve a bounded set of earlier evidence along with recent context so a slow scam does not lose its initial authority/threat clues. Limit verifier calls to meaningful new evidence, with one request in flight and a bounded retry policy. Rejected evidence should not trigger an endless loop.

Use structured JSON plus local schema validation and span checks. Give the verifier only transcript data, no tools, and instruct it to ignore commands embedded in speech. Mask sensitive identifiers using tested patterns and placeholders rather than indiscriminately replacing every digit. Validate returned spans against the redacted input and map them to originals locally. Names, addresses and spoken-number identifiers make perfect redaction unrealistic; document what is actually covered and what providers receive.

Choose the warning language explicitly at session start. Pre-generate and native-review Hindi and Telugu amber/red clips; add English as needed. Unlock audio on the Listen tap, provide a warning-audio test, and test whether playback is picked up by the microphone and causes a feedback warning. If capture must pause during playback, show that listening has paused and measure the resulting gap.

## Build schedule and milestone checks

Dates are fixed; hours are work blocks, not a promise that every task fits automatically. Reserve rest and submission buffer.

| When | Main work | Required evidence to move on |
|---|---|---|
| 29 Sep, first 2–3 focused hours | Read submission requirements; test API access/credits, browser microphone and actual sample rate, resampling to Sarvam input, Telugu-English and Hindi-English STT, schema validation, cached warning playback, deployed WebSocket | Real audio produces text and an audible warning on the intended device; transport/model choice recorded |
| 29 Sep, next 3–4 hours | Shared event contract, incremental detector, a small dev set containing positive and negative cases, minimal transcript/status UI | Scripted scam and “never share OTP” produce different outcomes; no future transcript access; duplicate segments do not inflate risk |
| 30 Sep, morning | Connect live capture to inference; two-device test; deploy working vertical slice | A fresh speakerphone role-play generates evidence and a warning through the deployed app |
| 30 Sep, afternoon | Polish listener and demo views, localized audio, evidence spans, user-controlled help links, sample-audio mode | Live, sample analysis and replay are labelled correctly; permission denial, slow API, disconnect and audio playback behave visibly |
| 30 Sep, evening | Complete dev evaluation, keyword baseline, family-separated dataset, content checks; tune on dev only | Frozen test manifest, documented metrics and configuration; cached inference distinguished from live latency |
| 1 Oct, morning | Audio/phone checks, fix critical issues, finish result view | Known false-positive cases covered; text and audio results separate; latency and failed sessions accounted for |
| 1 Oct, 1 PM | Freeze implementation and configuration; run untouched test set | Exported measured results with counts, misses and limitations; no threshold tuning after seeing test outcomes |
| 1 Oct, afternoon | Record demonstration, README, architecture, limitations, final links and artifacts | Clean-browser link check and final submission checklist completed |
| 1 Oct, 8 PM | Submit | Confirmation retained; buffer remains before 11:59 PM IST |

If a critical bug requires a post-test fix, disclose the rerun and that the test is no longer untouched. Do not present iterative tuning against it as a single held-out evaluation.

## Dashboard scope

Build one responsive application with three views, not three independent products.

- **Listener:** large status and native-language sentence, short evidence quotes, start/stop, audio control, user-initiated Call 1930 / Tell family / reporting-portal links. Test help actions without actually placing calls, sending messages or filing reports.
- **Demo:** unfolding transcript, evidence checklist, categorical warning timeline and compact listener preview. Show API health and timing in an expandable technical area. Render the first-ask marker and warning lead only for labelled samples or post-call review; a live app does not know the future ask.
- **Evaluation:** measured recall, false alarms, warned-before-ask, sample counts, language breakdown, and text/audio tabs. Start with static exported result JSON. Label results from synthetic scripts and small role-play recordings clearly.

Follow the deck's dark background and restrained gold accents. Risk status uses amber/red plus text and icons. A confidence-looking line with arbitrary values is less defensible than clear state changes and evidence markers. The deck's gold should not be confused with amber warnings.

Recommended soon: sample selection, manual “play warning” control, repeatable fixture validation, per-stage timing, and a concise failure list. Optional: animated phone mockup, replay speed controls, full call explorer, Langfuse and full-call LLM reference. The keyword baseline and basic evaluation view remain core.

## Teammate tasks that are genuinely small

The pasted 36-family + 160-example + 60-review + 20-recording allocation is substantial. Reduce initial assignments and expand only after the first delivery is checked. Assign language work by actual fluency.

| Person | First deliverable | Due | Acceptance check |
|---|---|---|---|
| Harshit | Review warning wording in languages he knows; verify submission fields; test one phone using a supplied checklist | 29 Sep wording/requirements; 30 Sep phone test | Four approved Hindi/Telugu warning sentences across fluent reviewers; exact browser/device and reproducible observations |
| Navadeep | Six scam outlines and six genuine look-alikes in a supplied template; label first dangerous ask or null | 30 Sep morning | Inspect all 12 for correct semantics, distinct families and plausible language |
| Both | Initially 6–10 consented role-play clips collectively, using reserved scripts, with speaker/language and ask timestamps | 30 Sep evening | Play and inspect every clip; disclose speaker overlap if it cannot be avoided |
| Both | Review approximately 10–15 generated transcripts each, limited to languages they understand | 30 Sep evening | Explicit accept/reject reason, corrected wording and label check |

We prepare templates, examples, validators, generation scripts, integration and result analysis. Validators catch missing fields and duplicate IDs, not whether labels or language are correct. An exemplar closer to another embedding class is a review flag, not proof of mislabelling. Bootstrap a small reviewed dev set immediately so teammate delivery never blocks the first vertical slice.

## Evaluation definitions

Freeze the family assignment before generating paraphrases. Keep dev exemplars, prompts and scripts separate from held-out families. If translations/paraphrases share a scenario, group them together. With only 6–10 audio clips, disclose any dev/test speaker overlap and avoid claims about unseen speakers.

For the promised dataset, plan 300 held-out transcripts plus a smaller separate dev set. If review/time constraints prevent this, prioritize a smaller credible benchmark and explicitly revise the achieved scope. Describe LLM-generated tests as synthetic coverage, not evidence of real-world scam prevalence or generalization. Report the reviewed proportion and do not silently discard model failures.

- **Primary alert threshold:** define confirmed red as primary; report amber separately so a conservative red result cannot hide nuisance amber warnings.
- **Scam recall:** scam calls with a qualifying alert divided by all scam test calls.
- **False-alarm rate:** genuine calls with a qualifying alert divided by all genuine test calls; show numerator and denominator.
- **Warned before ask:** scam calls whose alert was emitted before the labelled first money/credential ask divided by all scam calls with such an ask. Misses and late alerts fail. No-ask calls are reported separately.
- **Time to alert:** time from call start to actual alert emission, conditional on detection; report missed calls alongside the median.
- **Latency:** STT finalization, verification, and warning-render/playback delay, including buffering. Use uncached runs for latency; never reuse cached response times as fresh performance.
- **Lead time:** first-ask time minus emitted-alert time. Using the timestamp of the triggering quote would hide processing latency.

The keyword baseline receives the same incremental transcript and timing. The full-call LLM is an optional retrospective reference, not an early-warning competitor. Text scripts have synthetic timing; do not pass those results off as measured acoustic latency. Small audio and per-language subsets require counts and explicit uncertainty.

Six automated regression cases: digital-arrest pattern before money request; polite scam; “never share your OTP”; delivery OTP; repeated chunk; stop/start reset. Both OTP cases must pass through the complete detector. Mandatory manual smoke checks: provider failure/timeout, WebSocket disconnect, warning audio feeding back into the microphone, and a verifier response arriving after stop. Other scenarios can be checked manually as time permits.

## Cut order and completion standard

Cut fine-tuning, tracing integrations, extensive animation, call explorer, replay speeds and full-call LLM comparison first. Keep the dashboard compact and use a static evaluation export. If embeddings cannot run on the chosen host, measure a simpler verifier-based fallback and describe the architecture change honestly rather than claiming the two-stage cascade shipped.

Do not call the project complete merely because replay looks good. Completion requires a working fresh-audio inference path, evidence-backed warnings, an accessible listener view, visible failure handling, measured evaluation output, usable deployment/submission artifacts, and honest documentation of limitations. Two-device use and an internet connection remain prototype requirements.

## Sources checked for this review

- Accepted local deck: `/Users/cyril/Downloads/CallKavach_Idea_Deck.pdf`, especially slides 4–8. Deadline and same-problem constraint: user-supplied acceptance screenshots. Submission fields are still unverified.
- [Sarvam streaming STT](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api): documented modes and PCM/WAV input requirements; actual language accuracy and account access still need a spike.
- [W3C MediaStream Recording](https://www.w3.org/TR/mediastream-recording/): individual timeslice blobs need not be independently playable.
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output): schema constraints do not establish semantic correctness.
- [Render Free service limitations](https://render.com/docs/free): idle spin-down and ephemeral storage.
