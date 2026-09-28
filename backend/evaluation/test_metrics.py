"""Tests for offline red-alert metrics."""

import json
import unittest

from metrics import summarize_calls


def call(call_id, label, language="en", ask=None, alert=None):
    return {
        "call_id": call_id,
        "label": label,
        "language": language,
        "first_ask_at_ms": ask,
        "red_alert_at_ms": alert,
    }


class SummarizeCallsTests(unittest.TestCase):
    def test_alert_timing_recall_and_false_alarms(self):
        calls = [
            call("early", "scam", "te", 100, 30),
            call("equal", "scam", "te", 100, 100),
            call("late", "scam", "hi", 100, 150),
            call("missed", "scam", "hi", 100),
            call("no-ask", "scam", "en", alert=50),
            call("false-alarm", "genuine", "en", alert=20),
            call("correct-rejection", "genuine", "te"),
        ]
        original = json.dumps(calls)

        result = summarize_calls(calls)
        overall = result["overall"]
        self.assertEqual(overall["scam_recall"], {
            "numerator": 4, "denominator": 5, "rate": 0.8
        })
        self.assertEqual(overall["false_alarm_rate"], {
            "numerator": 1, "denominator": 2, "rate": 0.5
        })
        self.assertEqual(overall["warned_before_ask"], {
            "numerator": 1, "denominator": 4, "rate": 0.25
        })
        self.assertEqual(overall["median_time_to_alert_ms"], 75)
        self.assertEqual(overall["detected_scams"], 4)
        self.assertEqual(overall["missed_scams"], 1)
        self.assertEqual(overall["scams_without_ask"], 1)
        self.assertEqual(result["by_language"]["hi"]["warned_before_ask"]["rate"], 0)
        self.assertEqual(result["by_language"]["en"]["scams_without_ask"], 1)
        self.assertEqual(json.dumps(calls), original)
        json.dumps(result)

    def test_empty_denominators_are_null(self):
        empty = summarize_calls([])
        self.assertEqual(empty["by_language"], {})
        for key in ("scam_recall", "false_alarm_rate", "warned_before_ask"):
            self.assertEqual(empty["overall"][key], {
                "numerator": 0, "denominator": 0, "rate": None
            })
        self.assertIsNone(empty["overall"]["median_time_to_alert_ms"])

        genuine_only = summarize_calls([call("g", "genuine", "hi")])
        self.assertIsNone(genuine_only["by_language"]["hi"]["scam_recall"]["rate"])

    def test_rejects_invalid_records(self):
        valid = call("one", "scam", ask=0, alert=0)
        invalid_cases = [
            ([valid, valid.copy()], "duplicate call_id"),
            ([{**valid, "label": "unknown"}], "invalid label"),
            ([{**valid, "first_ask_at_ms": -1}], "invalid first_ask_at_ms"),
            ([{**valid, "red_alert_at_ms": -1}], "invalid red_alert_at_ms"),
            ([{key: value for key, value in valid.items() if key != "language"}],
             "missing language"),
        ]
        for records, message in invalid_cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                summarize_calls(records)


if __name__ == "__main__":
    unittest.main()
