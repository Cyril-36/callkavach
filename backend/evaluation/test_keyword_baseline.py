"""Tests for the incremental keyword baseline."""

import unittest

from backend.evaluation.keyword_baseline import first_keyword_alert


def segment(segment_id, end_at_ms, text, final=True):
    return {
        "segment_id": segment_id,
        "end_at_ms": end_at_ms,
        "text": text,
        "final": final,
    }


class FirstKeywordAlertTests(unittest.TestCase):
    def test_partial_and_duplicate_final_segments_are_ignored(self):
        segments = [
            segment("one", 10, "send OTP", final=False),
            segment("one", 20, "ordinary speech"),
            segment("one", 30, "send OTP"),
            segment("two", 40, "SEND otp"),
        ]
        self.assertEqual(first_keyword_alert(segments, ["send OTP"]), 40)

    def test_unicode_casefold_and_first_match(self):
        segments = [
            segment("one", 10, "Die STRASSE ist lang"),
            segment("two", 20, "straße"),
        ]
        self.assertEqual(first_keyword_alert(segments, ["straße"]), 10)

    def test_naive_baseline_flags_a_benign_otp_warning(self):
        warning = [segment("one", 25, "Never share OTP with anyone.")]
        self.assertEqual(first_keyword_alert(warning, ["OTP"]), 25)

    def test_no_match_and_empty_phrases(self):
        self.assertIsNone(first_keyword_alert([segment("one", 10, "hello")], ["OTP"]))
        self.assertIsNone(first_keyword_alert([segment("one", 10, "OTP")], []))
        with self.assertRaisesRegex(ValueError, "nonempty"):
            first_keyword_alert([], ["  "])


if __name__ == "__main__":
    unittest.main()
