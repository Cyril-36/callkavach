"""Tests for dev transcript and ground-truth separation."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.evaluation.validate_dev_set import validate_dev_set


DATA_DIR = Path(__file__).parent / "data"


def fixture():
    families = json.loads((DATA_DIR / "families.json").read_text(encoding="utf-8"))
    transcripts = []
    truth = []
    for family in families:
        call_id = f"dev-{family['family_id']}-001"
        transcripts.append({
            "call_id": call_id,
            "language": "en",
            "segments": [
                {"segment_id": "s1", "start_at_ms": 0, "end_at_ms": 1000,
                 "speaker": "caller", "text": "Hello.", "final": True},
                {"segment_id": "s2", "start_at_ms": 1200, "end_at_ms": 2000,
                 "speaker": "listener", "text": "Yes?", "final": True},
                {"segment_id": "s3", "start_at_ms": 2300, "end_at_ms": 3000,
                 "speaker": "caller", "text": "Please listen.", "final": True},
                {"segment_id": "s4", "start_at_ms": 3300, "end_at_ms": 4200,
                 "speaker": "caller", "text": "Send money." if family["label"] == "scam" else "Goodbye.",
                 "final": True},
            ],
        })
        truth.append({
            "call_id": call_id,
            "family_id": family["family_id"],
            "label": family["label"],
            "first_ask_at_ms": 3300 if family["label"] == "scam" else None,
        })
    return transcripts, truth, families


class ValidateDevSetTests(unittest.TestCase):
    def test_valid_fixture_does_not_mutate_inputs(self):
        data = fixture()
        original = deepcopy(data)
        self.assertIsNone(validate_dev_set(*data))
        self.assertEqual(data, original)

    def test_rejects_duplicate_and_mismatched_ids(self):
        transcripts, truth, families = fixture()
        transcripts[1]["call_id"] = transcripts[0]["call_id"]
        with self.assertRaisesRegex(ValueError, "duplicate transcript call_id"):
            validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        truth[0]["call_id"] = "different-id"
        with self.assertRaisesRegex(ValueError, "call IDs differ"):
            validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        truth[1]["family_id"] = truth[0]["family_id"]
        with self.assertRaisesRegex(ValueError, "duplicate dev family_id"):
            validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        transcripts[0]["segments"][1]["segment_id"] = "s1"
        with self.assertRaisesRegex(ValueError, "duplicate segment_id"):
            validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        truth[0]["family_id"] = "unknown-family"
        with self.assertRaisesRegex(ValueError, "unknown family_id"):
            validate_dev_set(transcripts, truth, families)

    def test_rejects_label_and_metadata_leakage(self):
        transcripts, truth, families = fixture()
        truth[0]["label"] = "genuine"
        with self.assertRaisesRegex(ValueError, "label disagrees"):
            validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        transcripts[0]["label"] = "scam"
        with self.assertRaisesRegex(ValueError, "unexpected label"):
            validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        truth[0]["red_alert_at_ms"] = 1000
        with self.assertRaisesRegex(ValueError, "unexpected red_alert_at_ms"):
            validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        del transcripts[0]["segments"][0]["start_at_ms"]
        with self.assertRaisesRegex(ValueError, "missing start_at_ms"):
            validate_dev_set(transcripts, truth, families)

    def test_rejects_bad_segment_timestamps_and_finality(self):
        for change, message in (
            ({"start_at_ms": -1}, "nonnegative integer"),
            ({"start_at_ms": 900}, "overlapping or unordered"),
            ({"end_at_ms": 1200}, "overlapping or unordered"),
            ({"final": False}, "finalized"),
        ):
            transcripts, truth, families = fixture()
            transcripts[0]["segments"][1].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                validate_dev_set(transcripts, truth, families)

    def test_rejects_invalid_first_ask_annotations(self):
        for ask in (None, -1, 1200, 9000):
            transcripts, truth, families = fixture()
            truth[0]["first_ask_at_ms"] = ask
            with self.subTest(ask=ask), self.assertRaises(ValueError):
                validate_dev_set(transcripts, truth, families)

        transcripts, truth, families = fixture()
        truth[1]["first_ask_at_ms"] = 0
        with self.assertRaisesRegex(ValueError, "null first ask"):
            validate_dev_set(transcripts, truth, families)


if __name__ == "__main__":
    unittest.main()
