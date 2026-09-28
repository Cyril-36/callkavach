# Navadeep's backend assignment

Owner: Navadeep Guduru (`Navadeep206`). Reviewer and merger: Chaitanya (`Cyril-36`). Target: a pull request by **30 September 2026, 2:00 PM IST**. This is a bounded **approximately 15–20% share of the backend work**, based on the planned backend components; it is an allocation estimate, not a measured percentage of code.

## Outcome

Build the **offline evaluation module** under `backend/evaluation/`. It measures the warning decisions made by CallKavach and provides a deliberately simple keyword baseline on the same unfolding transcripts. The main implementer will connect it to the live detector after reviewing your pull request. Your module must run without Sarvam, Gemini, API keys, network access, or the frontend.

This task replaces the earlier proposed set of 12 script outlines as your first priority. Add data or language review only after the backend pull request is ready and Chaitanya agrees.

## Files you own

- `backend/evaluation/metrics.py`: pure functions that compute the metrics below from a list of call records.
- `backend/evaluation/keyword_baseline.py`: a deterministic first-alert function for finalized transcript segments.
- `backend/evaluation/test_metrics.py` and `backend/evaluation/test_keyword_baseline.py`: meaningful `unittest` cases.
- `backend/evaluation/README.md`: a short example of both functions and their input/output format.

You may add `__init__.py` files needed to import the module. Keep all changes inside `backend/evaluation/` unless Chaitanya explicitly agrees to an interface change. Do not edit the audio capture, STT, Gemini verifier, risk rules, WebSocket server, frontend, root plan, or GitHub protection files. If another implementer creates a nearby backend package while you work, keep your PR to these files and note any integration point in its description.

## Exact interface

Expose `summarize_calls(calls: list[dict]) -> dict` in `metrics.py`. Each record has:

```json
{
  "call_id": "case-001",
  "label": "scam",
  "language": "te",
  "first_ask_at_ms": 192000,
  "red_alert_at_ms": 39000
}
```

`label` is `scam` or `genuine`. Times are nonnegative milliseconds from call start; `null` means no ask or no red alert. `language` is a short label supplied by the dataset, such as `en`, `hi`, `te`, or `code-mix`. The evaluator must not infer labels or ask times from transcript text. Reject invalid labels, negative times, duplicate call IDs, and missing required fields with a clear error. Do not mutate inputs.

Return JSON-compatible results with numerator, denominator, and rate for:

1. **Scam recall:** scam calls with a red alert / all scam calls.
2. **False-alarm rate:** genuine calls with a red alert / all genuine calls.
3. **Warned before ask:** scam calls with a non-null first ask and `red_alert_at_ms < first_ask_at_ms` / all scam calls with a non-null first ask. Missed, equal-time and late alerts fail. Scam calls with no ask are excluded and counted separately.
4. **Median time to alert:** median red-alert time among detected scam calls, with the detected/missed counts shown beside it. Return `null` for a rate or median with no eligible cases; never claim `0%` from an empty set.

Return a JSON-compatible object with `overall` and `by_language` keys. `overall` contains `scam_recall`, `false_alarm_rate`, and `warned_before_ask`, each as `{ "numerator": int, "denominator": int, "rate": float | null }`; it also contains `median_time_to_alert_ms` (`number | null`), `detected_scams`, `missed_scams`, and `scams_without_ask` counts. `by_language` maps each language label to an object with that same shape. Rates are fractions from 0 to 1, not formatted percentages. Do not present these numbers as real-world performance without a labelled test set.

Expose `first_keyword_alert(segments: list[dict], phrases: list[str]) -> int | None` in `keyword_baseline.py`. Each segment has `segment_id`, `end_at_ms`, `text`, and `final`. Read segments in supplied chronological order. Ignore non-final segments and duplicate finalized `segment_id` values. Use Unicode `casefold()` and substring matching against the explicit phrase list provided by the caller; reject empty phrases. Return the `end_at_ms` of the first matching finalized segment, or `None` if none match. The phrase list is supplied and frozen by the main implementer; do not invent or tune multilingual trigger lists against the held-out test set. This is intentionally a weak lexical baseline, so a phrase like “never share OTP” can be a false alarm. Document that limitation.

The baseline receives only transcript prefixes available at each point. It must not inspect future turns, ground-truth labels, or first-ask timestamps to decide when to alert. Later integration will feed its resulting alert time into `summarize_calls` using the same metric code as CallKavach.

## Acceptance checks

Use Python's standard library only. `python3 -m unittest discover -s backend/evaluation -p 'test_*.py'` must pass from the repository root. Cover at least: early/equal/late/missed alerts, a genuine false alarm, no eligible denominator, duplicate call ID rejection, a partial segment ignored, duplicate segment ignored, Unicode/case-insensitive matching, and an OTP warning that the naive keyword baseline flags. Include one small synthetic example in the README with exact expected counts.

Before opening the pull request, run `git diff --cached --check` after staging and confirm `git status` contains only the assigned files. The PR must describe its metric definitions, tests run, limitations, and any interface choice that Chaitanya should approve. **Do not merge it.** Chaitanya will review the code and logic and decide whether it matches the main detector and plan.

## Branch and pull request

Use your own Git identity on your machine. Start from the latest `main` and work on a dedicated branch:

```bash
git clone https://github.com/Cyril-36/callkavach.git
cd callkavach
git switch -c navadeep/backend-evaluation
# Make only the files assigned above.
python3 -m unittest discover -s backend/evaluation -p 'test_*.py'
git status --short
git add backend/evaluation
git diff --cached --check
git diff --cached --stat
git commit -m "Add offline backend evaluation metrics and keyword baseline"
git push -u origin navadeep/backend-evaluation
```

Open a pull request from `navadeep/backend-evaluation` into `main`, request `Cyril-36` as reviewer, and wait for his approval. If the repository is already cloned, start with `git switch main && git pull --ff-only origin main` before creating the branch. Never push directly to `main`, force-push the shared branch after review, merge your own PR, or commit `.env`, API keys, real call audio, or ordinary users' transcripts.
