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
        with self.assertRaisesRegex(ValueError, "pilot must cover"):
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


if __name__ == "__main__":
    unittest.main()
