# Detector events and results: contract for the evaluation runner

This is what `backend/evaluation/` can consume from the detector. Everything below is produced by code in `backend/spike/`. Metrics and their definitions belong to the evaluation module and are not implemented here.

## Two ways to get results

| Path | Use it for | Entry point | Time base |
|---|---|---|---|
| **Text replay** | dev and held-out transcript sets: detection, warned-before-ask, false alarms | `replay.replay_text_call(view, verifier)` | scripted segment end + measured processing |
| **Live end-to-end** | audio → STT → detector reliability, latency, cost, Stop behaviour | `e2e_harness.py` (report JSON) | the relay's session clock |

Report text and audio results separately. Replay has no Stop deadline, while the live path has one.

## Text replay: `callkavach.detector_replay.v1`

**Input.** Pass exactly the output of `backend/evaluation/detector_view.py`, holding **all** finalized segments of one call:

```json
{"language": "hi", "segments": [{"text": "...", "start_at_ms": 0, "end_at_ms": 4000}, ...]}
```

Any other key raises `ValueError` before anything reaches the verifier. That includes labels, `first_ask_at_ms`, `speaker`, IDs and extra segment fields. Segments must be in order.

**Behaviour.**
- Segments are fed one at a time with opaque IDs `r1`, `r2`, …; the model sees them as `seg1`, `seg2`, …. Each prefix is analysed before the next segment is fed.
- The production per-call timeout (8 s), validation and risk policy apply. `min_interval_s` is 0, because replay has no real-time spacing.

**Output** (one per call):

| Field | Meaning |
|---|---|
| `schema` | `"callkavach.detector_replay.v1"` |
| `clock` | `"scripted_end_plus_measured_processing"` |
| `final_level` | `none` \| `amber` \| `red`. `none` means no warning was raised, **not** "safe" |
| `analysis_status` | `complete`, or `incomplete` (a call failed, timed out, was rejected, or left segments unanalysed) |
| `first_warning_at_ms` | Emission time of the first amber-or-red event; `null` if none |
| `first_red_at_ms` | Emission time of the first red event; `null` if none |
| `errors` | Distinct error strings, such as timeouts, HTTP errors and rejected findings |
| `calls`, `reported_cost` | Analysis calls made, and the summed provider-reported cost (AICredits: INR) |
| `config` | `provider`, `model`, `call_timeout_s` |
| `summary` | The detector's final summary (see below) |
| `events` | Every `risk` event, in order |

**Rules for the runner (recommendations; the metric definitions are yours):**
- Compare `first_red_at_ms` (or `first_warning_at_ms`) against the ground-truth `first_ask_at_ms`, kept outside the view. Both are on the call's scripted clock.
- A call with `analysis_status != "complete"` is **not** a clean negative. Report failed or incomplete calls as their own count instead of scoring a missing warning as correct.
- Emission times include real model latency. Scripted segment times are **not** measured speech or STT timing.

## Live `risk` event (WebSocket, `type: "risk"`)

| Field | Meaning |
|---|---|
| `emitted_at_ms` | **Actual send time**, on the relay's session clock. It's stamped after the WebSocket send lock is acquired, immediately before the write |
| `first_warning_at_ms`, `first_red_at_ms` | Emission times of the first amber and first red event |
| `analysed_through_ms` | Receive time (same clock) of the newest segment the last successful analysis covered |
| `level`, `reason` | Deterministic level and the rule that set it. Never lowered during a session |
| `analysis` | `ok`, or `unavailable` (timeout, HTTP or transport error, malformed reply, **any** rejected finding, or exhausted call budget) |
| `error` | Reason text when `analysis` is `unavailable` |
| `tactics` | `[{tactic, evidence: [{segment_id, quote}]}]`: confirmed evidence only, with real segment IDs |
| `rejected_findings` | Findings rejected in this response. Any rejection fails the whole response |
| `analysed_segments`, `unanalysed_segments`, `calls` | Running counts |
| `latency_s` | Wall time of the analysis call that produced this event |
| `verifier` | `{provider, requested_model, returned_model, finish_reason, prompt_tokens, completion_tokens, cost, gateway_latency_ms}`, or `null` on failure |

## Summary (`stopped.analysis`, and `summary` in replay)

| Field | Meaning |
|---|---|
| `status` | `complete`; `incomplete` (a failure, or segments never analysed); `pending` (analysis still running at the Stop deadline, live only); or `unavailable` (no detector configured, live only, reported with `error`) |
| `cut_off_by_stop_deadline` | Live only. `true` when Stop's 6 s deadline ended the session while analysis was in flight. The in-flight result is discarded |
| `in_flight_for_s` | How long the cut-off call had been running |
| `level`, `reason`, `tactics` | Final state |
| `first_warning_at_ms`, `first_red_at_ms` | Same emission clock as the events |
| `analysed_segments`, `unanalysed_segments`, `calls`, `rejected_findings`, `error` | Counts, and the last error |

## Live end-to-end report: `callkavach.e2e_report.v1`

`e2e_harness.py --json` writes `{schema, config, runs, limitations}`.
- **`config`** records the mode (`production` or `measurement`), the analysis and HTTP timeouts, the Stop deadline, provider and model.
- **Each run** has the case, language and stop style, plus:
  - `transcripts`: segment ID, text, client time;
  - `risk_events` and `gaps`;
  - `errors`: provider or relay errors;
  - `stopped`: transcription completeness, reason, dropped audio, provider cleanup, utterance accounting;
  - `analysis`, the summary above;
  - `client_timing`: speech end, first transcript, Stop sent, end, and Stop-to-end, in seconds on the client's clock;
  - `detection`: final level, first warning and red times, status, cut-off, calls, per-call latencies, reported cost.

Client times (seconds since connect) and server times (session milliseconds) are separate clocks. Don't subtract one from the other.

**Never pool `production` and `measurement` runs.** Measurement mode raises the analysis and HTTP timeouts to 30 s to observe latency, so it says nothing about reliability under the production 8 s timeout.
