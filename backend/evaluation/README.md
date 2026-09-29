# Offline evaluation

The metrics, keyword baseline and validators use only Python's standard library.
The optional replay runner invokes the separately configured live detector,
which may call an external verifier.

Run the checks from the repository root:

```bash
python3 -m unittest discover -s backend/evaluation -p 'test_*.py'
```

## Development replay runner

`replay_runner.py` schedules each **finalized** pilot segment at its scripted
end time. At each step, `detector_view()` supplies only the visible prefix;
the runner creates an opaque per-session segment ID and a real monotonic
receive time for the detector. It captures the detector's actual emitted
`risk` events, then joins the separate ground truth after that call closes.
The first `red` event's `emitted_at_ms` becomes `red_alert_at_ms` for the
existing metrics. Missing alerts stay null. The report includes genuine false
alarms, scam recall, red warning before the scripted first ask, verifier latency,
post-receive delay, and detector failures. Failed calls remain in metric
denominators and are counted separately.

The command below requires the main implementer's detector (PR #10) to be
merged and a configured AICredits verifier. Until then it exits without
producing results. Run from the repository root and save the output outside
the repository:

```bash
python3 -m backend.evaluation.run_pilot --output /tmp/callkavach-dev-replay.json
```

This is a **synthetic text replay**. Scripted segment and first-ask times are
not measured speech or STT timing. `emitted_at_ms` and the processing delays
come from the detector's actual replay clock; they are not audio-to-warning
latency. Independent language review of these development calls is pending,
so any tuning or score from them is provisional. Never feed the sealed final
families to this development runner or tune after seeing their results.

## Example

```python
from backend.evaluation.metrics import summarize_calls
from backend.evaluation.keyword_baseline import first_keyword_alert

calls = [
    {"call_id": "scam-1", "label": "scam", "language": "en",
     "first_ask_at_ms": 100, "red_alert_at_ms": 40},
    {"call_id": "scam-2", "label": "scam", "language": "en",
     "first_ask_at_ms": 80, "red_alert_at_ms": None},
    {"call_id": "genuine-1", "label": "genuine", "language": "en",
     "first_ask_at_ms": None, "red_alert_at_ms": 20},
]
results = summarize_calls(calls)

segments = [
    {"segment_id": "one", "end_at_ms": 10,
     "text": "Never share", "final": False},
    {"segment_id": "one", "end_at_ms": 25,
     "text": "Never share OTP", "final": True},
]
baseline_alert_at_ms = first_keyword_alert(segments, ["OTP"])  # 25
```

For these three synthetic calls, `results["overall"]` is exactly:

```json
{
  "scam_recall": {"numerator": 1, "denominator": 2, "rate": 0.5},
  "false_alarm_rate": {"numerator": 1, "denominator": 1, "rate": 1.0},
  "warned_before_ask": {"numerator": 1, "denominator": 2, "rate": 0.5},
  "median_time_to_alert_ms": 40,
  "detected_scams": 1,
  "missed_scams": 1,
  "scams_without_ask": 0
}
```

`results["by_language"]["en"]` has the same values because every example call
uses `en`. Rates are fractions; an empty denominator produces `null`. The median
uses only detected scam calls and is measured from call start to the emitted red
alert. An alert must be strictly earlier than the labelled first ask to count as
"warned before ask". Calls with no ask are excluded from that denominator and
counted separately.

The caller supplies ground-truth labels, language labels, ask times and actual
red-alert emission times. The evaluator does not infer them from transcripts.
The main implementer supplies and freezes the baseline phrase list. Feed only
the transcript prefix available at each point, in chronological order; partial
segments and repeated finalized segment IDs are ignored. A substring baseline
cannot understand context: the benign warning "Never share OTP" triggers the
`OTP` phrase. These synthetic examples are not real-world performance claims.

## Scenario-family seeds

`data/families.json` contains 12 hand-written English outlines: one scam and one
genuine look-alike for each of six scenario types. Every outline has 3–6 ordered
caller steps. `first_dangerous_ask_step` is the zero-based index of the first
request for money, banking credentials, an OTP/PIN, or remote access in a scam;
it is `null` for genuine calls. The courier's genuine delivery code is for the
order handoff, not a banking OTP, so that outline has a null dangerous ask.

Validate the file from the repository root with:

```bash
python3 backend/evaluation/validate_families.py
```

The validator checks fields, labels, scenario pairs, step counts, IDs and ask
index bounds. It cannot establish whether a line sounds natural, whether a
label is correct, or whether the marked ask is semantically the first dangerous
one. Chaitanya must review all 12 outlines. These are synthetic seeds, not full
transcripts, a frozen test set, or measured detector results. Do not generate
the planned held-out transcripts from them until the owner freezes the family
split.

## English development call timelines

`data/dev_transcripts.json` contains one complete, synthetic English dialogue
for each of the 12 existing families. Each call has a stable `call_id`, an `en`
language label, and ordered finalized caller/listener segments with start and
end times in milliseconds. `data/dev_ground_truth.json` holds the matching
`call_id`, `family_id`, `label`, and `first_ask_at_ms` **separately**. Join these
files by `call_id` only for evaluation; feed only transcript segments (and the
chosen language) to a detector. Never pass the ground-truth file, family ID,
label, or first-ask time into detection.

Run the local validator from the repository root:

```bash
python3 backend/evaluation/validate_dev_set.py
python3 -m unittest discover -s backend/evaluation -p 'test_*.py'
```

For scam calls, `first_ask_at_ms` marks the **start** of the caller segment
containing the first explicit request for money, banking credentials, OTP/PIN,
or remote access. It is `null` for genuine calls. The KYC genuine call says
“Never share your OTP,” and the courier genuine call exchanges an order-specific
delivery code; both are intentional benign counterexamples. The validator
checks structure, ID alignment, timestamp order, finalized segments, family
labels, and that a scam ask starts a caller segment. It cannot prove the words
are natural or that the marked segment is semantically the first dangerous ask;
those 12 calls need human review.

These are authored text timelines with **synthetic timing**, not audio latency
measurements or a held-out test. Neither file contains alert timestamps. Only
an actual detector run may produce `red_alert_at_ms`; join that emitted time
with ground truth by `call_id` before calling `summarize_calls`. Do not fill in
an alert time from the script or assume that a detector warned because a scam
label is present.

## Multilingual development pilot

`data/multilingual_pilot_transcripts.json` and
`data/multilingual_pilot_ground_truth.json` contain ten **candidate** calls:
digital-arrest and KYC scam/genuine pairs in both Hindi-English and
Telugu-English, plus a Telugu-English courier pair. Opaque call IDs join
raw transcript fixtures to evaluator-only family lineage, labels and first
asks. All families are on the development side. Independent fluent-speaker
review is pending; see `MULTILINGUAL_PILOT_REVIEW.md`.

The raw transcript JSON is an **evaluation fixture, not detector input**.
For each newly finalized turn, use `detector_view` to create a bounded prefix:

```python
from backend.evaluation.detector_view import detector_view

for count in range(1, len(transcript["segments"]) + 1):
    prefix = detector_view(transcript, count)
    # Send only prefix to the incremental detector; never the raw fixture.
```

The projection includes only `language` and ordered segment `text`,
`start_at_ms`, and `end_at_ms`. It excludes call IDs, speakers, labels,
lineage, first asks and future turns. Never send raw fixtures or ground truth
to a verifier. Segment-start first-ask times are coarse scripted annotations, not
measured speech or detector alert times. Only an actual detector run may
produce alert timestamps.

```bash
python3 backend/evaluation/validate_multilingual_pilot.py
python3 -m unittest discover -s backend/evaluation -p 'test_*.py'
```
