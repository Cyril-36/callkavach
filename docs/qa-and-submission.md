# Offline QA and submission evidence — 1 October 2026

Scope: Harshit's non-API handoff on `harshit/non-api-handoff`, based on `main` commit `e04bba5a1b8fc33556535d99e0155fd57b7fbbf9`. No live provider call, real call audio, deployed test, or held-out evaluation result was used here. Commands below were run from the repository root on Windows with Python and Node already installed.

## Offline checks actually run

| Check | Command or method | Observed result |
| --- | --- | --- |
| Evaluation unit tests | `python -m unittest discover -s backend/evaluation -p 'test_*.py'` | 36 passed. |
| Multilingual development pilot structure | `python backend/evaluation/validate_multilingual_pilot.py` | Validated ten pilot calls. This is structural validation, not human language approval. |
| Development set structure | `python backend/evaluation/validate_dev_set.py` | Validated 12 development calls. |
| Browser audio transport unit tests | `node --test frontend/spike/resample.test.js frontend/spike/pcm-sender.test.js` | 15 passed after rerunning outside the restricted process sandbox; first attempt could not spawn Node workers (`EPERM`). No frontend files were changed. |
| Backend spike tests | `python -m pytest -q backend/spike -p pytest_asyncio -p no:cacheprovider --disable-warnings --tb=short` with temporary `pytest-asyncio` on `PYTHONPATH` | 161 passed, 2 setup/teardown errors. Pytest's `PYTEST_CURRENT_TEST` update raised `ValueError: the environment variable is longer than 32767 characters` for two long parameter names in `test_invalid_frames_are_rejected`; those two test bodies did not execute. A focused run excluding that parametrized test yielded 159 passed, 3 deselected. This is **not** a wholly passing backend suite. The dependency was installed to a temporary directory, not to the repository. |
| Static warning clips | Python `wave` read all six `assets/warnings/*.wav`; Windows `System.Media.SoundPlayer.PlaySync()` played each | Revised Piper clips decoded as mono 22,050 Hz, 16-bit PCM and played locally without error. Harshit, confirming fluency in Hindi and Telugu, approved the four language clips' wording, pauses and pronunciation. English pronunciation and browser/phone playback remain pending. |
| Browser capture lifecycle | Served `backend/spike/audio_ws.py` locally with `STT_PROVIDER=mock` and `LLM_PROVIDER=off`, then opened `http://127.0.0.1:8766/lifecycle.test.html` in the in-app browser. | The first run reported **14 failures**, each a timeout with status still `Listening ...`. A visible in-app browser retry also timed out after reaching `Listening`; the server accepted a WebSocket but the page did not show received samples. The test uses a synthetic oscillator; it did not capture real microphone audio or call a provider. The cause remains undiagnosed, so browser lifecycle QA has not passed. |

## Device and submission checklist

| Item | Status / evidence needed |
| --- | --- |
| Public deployed URL and integrated commit | Pending Cyril's URL and integration. No deployed URL has been supplied. |
| Second-device phone test | Pending deployed URL. Record phone model/OS, browser/version, date, and whether the test speech was synthetic or consented. |
| Permission denial, disconnect, Stop → Start, warning playback, help link | Pending phone test. Record each observed outcome, including failures and any Stop cut-off as pending analysis. |
| Hindi and Telugu warning wording and clip pronunciation | Approved by Harshit-ambati as a fluent Hindi/Telugu speaker on 1 October 2026; see `docs/warning-copy.md`. Device playback remains pending. |
| Ten pilot calls' language and label acceptance | Pending Harshit's call-by-call decisions as a fluent Hindi/Telugu reviewer; see `docs/pilot-language-review.md`. No call is marked accepted. |
| Measured latency, recall, false alarm, costs and provider failures | Pending Cyril's measured export. Text replay and mock QA cannot substantiate a live audio timing or accuracy claim. |
| Final README | Current `README.md` still says the repository contains only planning and lacks a working listener, although `backend/` and `frontend/spike/` code now exist. Cyril should update the product and deployment description after integration; this handoff does not change README. |
| Demo, public links, and final submission receipt | Pending Cyril's evidence. No demo or submission claim has been verified. |

## Independent PR review for Cyril

Reviewed the diffs against `main` at the following heads. This record is **not** a GitHub approval. The findings were also posted on [PR #11](https://github.com/Cyril-36/callkavach/pull/11#issuecomment-5925717020) and [PR #12](https://github.com/Cyril-36/callkavach/pull/12#issuecomment-5925721901) for Cyril.

### [PR #11 — evaluation runner](https://github.com/Cyril-36/callkavach/pull/11), head `565f9cef`

- **Action requested:** `backend/evaluation/run_pilot.py` says to save the report outside the repository, but accepts any `--output` path and writes transcript text and evidence quotes there. Add a path guard comparable to PR #12's `report_path_error`, or otherwise prevent an in-repository report, before a live development replay. Do not check such a report into Git.
- The runner feeds `detector_view` prefixes and adds `call_id`/truth to the result only after detection. I found no future-label input to the detector in this diff. It distinguishes emitted red alerts from amber warning rates, and exposes `failure_calls`. It still includes failed calls in rate denominators by definition; present failure counts alongside rates so an incomplete session is not described as a clean negative. Its timing basis is synthetic text replay with a real detector clock, not live audio latency.
- The PR remains a **draft**. No approval or merge is recommended until Cyril reviews the contract and a measured run is honestly labelled.

### [PR #12 — reliability](https://github.com/Cyril-36/callkavach/pull/12), head `18fa850`

- The Stop summary now sets `cut_off_by_stop_deadline` when detector status is pending and describes in-flight/queued segments. The report extracts that flag. I did not find code that deliberately scores such a Stop as a clean negative. A consumer of the report still needs to exclude or explicitly flag these cases when making performance claims.
- **Action requested:** `backend/spike/e2e_harness.py` always labels `detection.cost_unit` as `INR (AICredits usage.cost)`, even though verifier selection can be `gemini`; the report should take the unit from the actual provider metadata or leave it unspecified when unavailable. Otherwise a Gemini run can carry an unsupported cost label. The existing harness test checks the number but does not cover the provider/unit combination.
- The harness correctly refuses an in-repository JSON report by default. Its documented sample cases and synthetic relay test do not establish two-device or live human-speech results. I made no live provider run and cannot approve live reliability claims from this review alone.

## Merge access observed

The authenticated GitHub permission endpoint returned `write` for `Harshit-ambati`. At this check, PR #11 was draft and PR #12 reported `mergeable: MERGEABLE`, `mergeStateStatus: BLOCKED`, and `reviewDecision: REVIEW_REQUIRED`; its GitGuardian check had succeeded. Write permission allows Harshit to operate an eligible merge, but PR #12 is currently blocked by required review. Cyril's current code-owner approval and the other branch-rule conditions remain necessary. No merge was attempted.
