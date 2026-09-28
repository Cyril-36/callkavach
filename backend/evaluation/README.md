# Offline evaluation

This standard-library-only module evaluates labelled call records and provides a
simple keyword baseline over finalized transcript segments. It makes no API calls.

Run the checks from the repository root:

```bash
python3 -m unittest discover -s backend/evaluation -p 'test_*.py'
```

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
