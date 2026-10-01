# Offline QA and submission evidence — 1 October 2026

Scope: Harshit's non-API handoff on `harshit/non-api-handoff`, based on `main` commit `e04bba5a1b8fc33556535d99e0155fd57b7fbbf9`. No live provider call, real call audio, deployed test, or held-out evaluation result was used here. Commands below were run from the repository root on Windows with Python and Node already installed.

This file preserves earlier results as run history. The latest offline check on merged `main` is recorded at the end; its passing browser lifecycle result supersedes the earlier synthetic-browser timeout. The deployed phone checks remain pending.

## Offline checks actually run

| Check | Command or method | Observed result |
| --- | --- | --- |
| Evaluation unit tests | `python -m unittest discover -s backend/evaluation -p 'test_*.py'` | 36 passed. |
| Multilingual development pilot structure | `python backend/evaluation/validate_multilingual_pilot.py` | Validated ten pilot calls. This is structural validation, not human language approval. |
| Development set structure | `python backend/evaluation/validate_dev_set.py` | Validated 12 development calls. |
| Browser audio transport unit tests | `node --test frontend/spike/resample.test.js frontend/spike/pcm-sender.test.js` | 15 passed after rerunning outside the restricted process sandbox; first attempt could not spawn Node workers (`EPERM`). No frontend files were changed. |
| Merged PR #12 cost-unit tests | `python -m pytest -q backend/spike/test_replay_and_harness.py -k 'cost_unit or harness_summarise' -p pytest_asyncio -p no:cacheprovider --disable-warnings --tb=short` with temporary `pytest-asyncio` on `PYTHONPATH` | 2 passed, 16 deselected on the updated `main` checkout; offline only. |
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
| Ten pilot calls' language and label acceptance | Harshit-ambati confirmed reading all ten complete calls and accepted every call's language, scam/genuine label and first-dangerous-ask annotation without corrections on 1 October 2026; see `docs/pilot-language-review.md`. |
| Measured latency, recall, false alarm, costs and provider failures | Pending Cyril's measured export. Text replay and mock QA cannot substantiate a live audio timing or accuracy claim. |
| Final README | Current `README.md` still says the repository contains only planning and lacks a working listener, although `backend/` and `frontend/spike/` code now exist. Cyril should update the product and deployment description after integration; this handoff does not change README. |
| Demo, public links, and final submission receipt | Pending Cyril's evidence. No demo or submission claim has been verified. |

## Independent PR review for Cyril

Reviewed the diffs against `main` at the following heads. This record is **not** a GitHub approval. The findings were also posted on [PR #11](https://github.com/Cyril-36/callkavach/pull/11#issuecomment-5925717020) and [PR #12](https://github.com/Cyril-36/callkavach/pull/12#issuecomment-5925721901) for Cyril. The follow-up below was checked against `main` at `727b151` and PR #11 head `f2e6cad`.

### [PR #11 — evaluation runner](https://github.com/Cyril-36/callkavach/pull/11), initial head `565f9cef`, current head `f2e6cad`

- **Resolved in newer draft head `f2e6cad`:** `backend/evaluation/run_pilot.py` now rejects an output path inside the repository before verifier setup, including a symlink resolving into the repository, and adds an offline test. This addresses the original report-path finding. I have not run a live replay.
- The runner feeds `detector_view` prefixes and adds `call_id`/truth to the result only after detection. I found no future-label input to the detector in this diff. It distinguishes emitted red alerts from amber warning rates, and exposes `failure_calls`. It still includes failed calls in rate denominators by definition; present failure counts alongside rates so an incomplete session is not described as a clean negative. Its timing basis is synthetic text replay with a real detector clock, not live audio latency.
- The PR remains an **open draft** at this check. Cyril still needs to review its current head and any measured run must be honestly labelled.

### [PR #12 — reliability](https://github.com/Cyril-36/callkavach/pull/12), initial head `18fa850`, merged head `90a24ba`

- The Stop summary now sets `cut_off_by_stop_deadline` when detector status is pending and describes in-flight/queued segments. The report extracts that flag. I did not find code that deliberately scores such a Stop as a clean negative. A consumer of the report still needs to exclude or explicitly flag these cases when making performance claims.
- **Resolved in merged head `90a24ba`:** `backend/spike/e2e_harness.py` now reports the INR/AICredits unit only when every cost-bearing verifier record identifies AICredits; otherwise it leaves the unit unspecified. Added tests cover absent and Gemini provenance. Cyril merged PR #12 into `main` as `727b151` on 1 October 2026.
- The harness correctly refuses an in-repository JSON report by default. Its documented sample cases and synthetic relay test do not establish two-device or live human-speech results. I made no live provider run and cannot approve live reliability claims from this review alone.

## Merge access observed

The authenticated GitHub permission endpoint returned `write` for `Harshit-ambati`. Cyril merged [PR #16](https://github.com/Cyril-36/callkavach/pull/16) and [PR #12](https://github.com/Cyril-36/callkavach/pull/12) on 1 October 2026; GitHub identifies `Cyril-36` as `mergedBy` for both. PR #11 is still an open draft at head `f2e6cad`. Harshit did not attempt a merge.

## Later owner integration on 1 October 2026

The PR status above describes Harshit's check at `f2e6cad`. Cyril subsequently reviewed and merged PR #11 as `9fb7274` and PR #17 as `f2a5b0e`. The development runner's 47 offline tests and ten-call structural validator passed; no additional paid-provider run was made. The rebased listener passed 190 offline backend tests and 31 Node tests. In Cyril's Chrome mock browser check, three listener lifecycle cases passed; the automated Start → Stop → Start case timed out waiting for a synthetic transcript. This is an unresolved browser-test limitation, not a passing device result. The public deployment, two-device test, and measured provider evaluation remain pending.

## Listener lifecycle retest

The missing transcript was traced to the lifecycle page launching its synthetic microphone with a programmatic click on page load. Chrome suspended both test AudioContexts, so no PCM frames reached the mock relay. The test page now waits for a real click on **Run lifecycle tests**. With `STT_PROVIDER=mock LLM_PROVIDER=off`, all four listener lifecycle cases passed on two Chrome runs, including Start → Stop → Start with a transcript and confirmed `stopped` reply in each session. The app's capture code was unchanged, and all 31 Node tests passed. This resolves the synthetic test-harness failure; it does not replace the pending phone, two-device, or live-provider checks.

## Harshit's offline QA on merged `main` (`d314bdf`)

Checked on 1 October 2026 after Cyril merged PR #20. The server used `STT_PROVIDER=mock` and `LLM_PROVIDER=off`; no paid provider, real call, or held-out evaluation material was used. This is a new run, separate from the historical results above.

| Check | Exact command or action | Observed result |
| --- | --- | --- |
| Evaluation unit tests | `python -m unittest discover -s backend/evaluation -p 'test_*.py'` | 47 passed on rerun. The first restricted run had one Windows `PermissionError` creating a test symlink in `%TEMP%`; rerunning with permission completed all 47. |
| Ten-call development validator | `python backend/evaluation/validate_multilingual_pilot.py` | Validated ten candidate multilingual development calls. This does not replace Harshit's recorded human review. |
| Public-host, access-code and quota tests | `$env:PYTHONPATH = Join-Path $env:TEMP 'callkavach-testdeps'; python -m pytest -q backend/spike/test_audio_ws.py -k 'public_host or access_code or hourly or deployment_config or relay_refuses' -p pytest_asyncio -p no:cacheprovider --disable-warnings --tb=short` | 35 passed, 81 deselected. The temporary dependency path is outside the repository. |
| Listener and audio transport tests | `node --test frontend/app/session-core.test.js frontend/spike/resample.test.js frontend/spike/pcm-sender.test.js` | 32 passed. |
| Listener browser lifecycle | Set `$env:STT_PROVIDER='mock'; $env:LLM_PROVIDER='off'`, then ran `python -m uvicorn --app-dir backend/spike audio_ws:app --host 127.0.0.1 --port 8767`; opened `/lifecycle.test.html` in the in-app browser and clicked **Run lifecycle tests**. | Page title `ALL PASSED`; 4/4 cases passed, including Start → Stop → Start with a synthetic transcript and a confirmed server Stop. The temporary server was stopped afterward. |

PR #20's merged public-host configuration was checked only through offline tests. Its deployment, real-provider behavior and phone experience are not verified by these results.

## Deployed phone QA record — pending Cyril's URL

Fill this record only from an observed run. Use synthetic or explicitly consented speech. Keep recordings, ordinary transcripts, keys, access codes and live-result reports out of Git; record a private evidence location instead of copying them here.

| Run field | Observed value |
| --- | --- |
| Public HTTPS URL and deployed commit | Pending — no URL supplied to Harshit at this check |
| Date/time (IST), phone model, OS and browser/version | Pending |
| Input source and consent/synthetic status | Pending |
| Access-code configuration and session-cap behavior | Pending; do not record the code itself |

| Phone check | Observed result | Private evidence reference |
| --- | --- | --- |
| Page loads over HTTPS; permission allowed; second-device listening starts | Pending | Pending |
| Microphone permission denied; page clearly says it is not listening | Pending | Pending |
| Microphone or network disconnect; warning status does not imply a safe call | Pending | Pending |
| Stop → Start creates a fresh session; note whether Stop was confirmed or analysis cut off | Pending | Pending |
| Amber and red warning playback in Hindi, Telugu and English; on-screen fallback if sound fails | Pending | Pending |
| `tel:1930` and `cybercrime.gov.in` help links open the intended destination without automatic reporting | Pending | Pending |
| Final README, demo, evaluation counts/failures, public links and submission receipt match observed evidence | Pending | Pending |
