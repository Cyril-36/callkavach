"""Regression checks for the multilingual candidate pilot."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.evaluation.validate_multilingual_pilot import validate_pilot


DATA_DIR = Path(__file__).parent / "data"


def fixture():
    names = (
        "multilingual_pilot_transcripts.json",
        "multilingual_pilot_ground_truth.json",
        "families.json",
        "dev_transcripts.json",
        "heldout_family_outlines.json",
    )
    return [json.loads((DATA_DIR / name).read_text(encoding="utf-8")) for name in names]


class MultilingualPilotTests(unittest.TestCase):
    def test_repository_pilot_is_valid_and_unmodified(self):
        data = fixture()
        original = deepcopy(data)
        self.assertIsNone(validate_pilot(*data))
        self.assertEqual(data, original)

    def test_rejects_duplicate_and_reused_ids(self):
        data = fixture()
        data[0][1]["call_id"] = data[0][0]["call_id"]
        with self.assertRaisesRegex(ValueError, "duplicate or reused call_id"):
            validate_pilot(*data)
        data = fixture()
        data[0][0]["call_id"] = data[3][0]["call_id"]
        with self.assertRaisesRegex(ValueError, "opaque pilot ID"):
            validate_pilot(*data)
        data = fixture()
        data[3][0]["call_id"] = data[0][0]["call_id"]
        with self.assertRaisesRegex(ValueError, "duplicate or reused call_id"):
            validate_pilot(*data)

    def test_rejects_timing_finality_and_truth_leakage(self):
        for field, value, message in (
            ("start_at_ms", -1, "nonnegative integer"),
            ("start_at_ms", 4000, "overlapping or unordered"),
            ("final", False, "finalized"),
        ):
            data = fixture()
            data[0][0]["segments"][1][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, message):
                validate_pilot(*data)
        data = fixture()
        data[0][0]["label"] = "scam"
        with self.assertRaisesRegex(ValueError, "unexpected label"):
            validate_pilot(*data)

    def test_rejects_wrong_pair_and_ask(self):
        data = fixture()
        data[1][0]["pair_group_id"] = "other"
        with self.assertRaisesRegex(ValueError, "pair_group_id disagrees"):
            validate_pilot(*data)
        data = fixture()
        data[1][0]["first_ask_at_ms"] = 24800
        with self.assertRaisesRegex(ValueError, "first ask must start a caller segment"):
            validate_pilot(*data)
        data = fixture()
        data[1][1]["first_ask_at_ms"] = 0
        with self.assertRaisesRegex(ValueError, "null first ask"):
            validate_pilot(*data)
        data = fixture()
        data[1][0]["family_id"] = data[4][0]["family_id"]
        with self.assertRaisesRegex(ValueError, "non-development family"):
            validate_pilot(*data)

    def test_rejects_missing_pair_or_wrong_language(self):
        data = fixture()
        data[0][1]["language"] = "te-en"
        with self.assertRaisesRegex(ValueError, "duplicate genuine"):
            validate_pilot(*data)
        data = fixture()
        data[1][1]["label"] = "scam"
        with self.assertRaisesRegex(ValueError, "label disagrees"):
            validate_pilot(*data)

    def test_rejects_dev_heldout_pair_overlap(self):
        data = fixture()
        data[4][0]["pair_group_id"] = "kyc-update-seed-01"
        with self.assertRaisesRegex(ValueError, "pair-group IDs overlap"):
            validate_pilot(*data)

    def test_scripted_ask_locations_match_reviewed_request_lines(self):
        transcripts, truth, *_ = fixture()
        calls = {call["call_id"]: call for call in transcripts}
        expected = {
            "p-4c2e9a10": (7, "₹18,000"),
            "p-0f6a52c8": (5, "banking OTP"),
            "p-a91c407e": (6, "₹12,000"),
            "p-5e3b10a7": (8, "banking OTP"),
            "p-19f0c65b": (7, "₹2,500"),
        }
        for record in truth:
            if record["label"] == "genuine":
                self.assertIsNone(record["first_ask_at_ms"])
                continue
            index, request_phrase = expected[record["call_id"]]
            segment = calls[record["call_id"]]["segments"][index - 1]
            self.assertEqual(record["first_ask_at_ms"], segment["start_at_ms"])
            self.assertIn(request_phrase, segment["text"])

    def test_turn_count_and_ask_position_are_varied(self):
        transcripts, truth, *_ = fixture()
        lengths = {len(call["segments"]) for call in transcripts}
        self.assertGreaterEqual(len(lengths), 4)
        self.assertTrue(any(
            first["speaker"] == second["speaker"]
            for call in transcripts
            for first, second in zip(call["segments"], call["segments"][1:])
        ))
        calls = {call["call_id"]: call for call in transcripts}
        ask_positions = {
            next(index for index, segment in enumerate(calls[item["call_id"]]["segments"], 1)
                 if segment["start_at_ms"] == item["first_ask_at_ms"])
            for item in truth if item["label"] == "scam"
        }
        self.assertGreaterEqual(len(ask_positions), 3)


if __name__ == "__main__":
    unittest.main()
