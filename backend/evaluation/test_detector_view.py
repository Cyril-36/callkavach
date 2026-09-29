"""Detector input must be a prefix with no answer or identity metadata."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.evaluation.detector_view import detector_view


DATA_DIR = Path(__file__).parent / "data"


class DetectorViewTests(unittest.TestCase):
    def test_every_pilot_prefix_is_minimal_and_has_no_future_turns(self):
        calls = json.loads((DATA_DIR / "multilingual_pilot_transcripts.json").read_text(encoding="utf-8"))
        truth = json.loads((DATA_DIR / "multilingual_pilot_ground_truth.json").read_text(encoding="utf-8"))
        truth_by_id = {item["call_id"]: item for item in truth}
        for call in calls:
            original = deepcopy(call)
            for count in range(len(call["segments"]) + 1):
                view = detector_view(call, count)
                with self.subTest(call=call["call_id"], count=count):
                    self.assertEqual(set(view), {"language", "segments"})
                    self.assertEqual(len(view["segments"]), count)
                    self.assertEqual(view["language"], call["language"])
                    for source, projected in zip(call["segments"][:count], view["segments"]):
                        self.assertEqual(set(projected), {"text", "start_at_ms", "end_at_ms"})
                        self.assertEqual(projected["text"], source["text"])
                    serialized = json.dumps(view, ensure_ascii=False)
                    for forbidden in (
                        call["call_id"], truth_by_id[call["call_id"]]["family_id"],
                        truth_by_id[call["call_id"]]["pair_group_id"],
                        "first_ask_at_ms", '"label"', '"speaker"', '"call_id"',
                        '"segment_id"', '"final"',
                    ):
                        self.assertNotIn(forbidden, serialized)
                    if count < len(call["segments"]):
                        self.assertNotIn(call["segments"][count]["text"], serialized)
            self.assertEqual(call, original)

    def test_answer_bearing_raw_ids_are_stripped(self):
        call = {
            "call_id": "scam-kyc-answer-in-id",
            "family_id": "secret-family",
            "label": "scam",
            "language": "hi-en",
            "first_ask_at_ms": 9000,
            "segments": [
                {"segment_id": "scam-s1", "speaker": "caller", "text": "First available turn.",
                 "start_at_ms": 0, "end_at_ms": 1000, "final": True},
                {"segment_id": "s2", "speaker": "listener", "text": "FUTURE_SENTINEL",
                 "start_at_ms": 1100, "end_at_ms": 2000, "final": True},
            ],
        }
        view = detector_view(call, 1)
        self.assertEqual(view, {"language": "hi-en", "segments": [
            {"text": "First available turn.", "start_at_ms": 0, "end_at_ms": 1000}
        ]})
        self.assertNotIn("FUTURE_SENTINEL", json.dumps(view))

    def test_nonfinal_segments_are_hidden_and_count_is_bounded(self):
        call = {"language": "te-en", "segments": [
            {"text": "partial", "start_at_ms": 0, "end_at_ms": 100, "final": False},
            {"text": "finalized", "start_at_ms": 0, "end_at_ms": 200, "final": True},
        ]}
        self.assertEqual(detector_view(call, 1)["segments"][0]["text"], "finalized")
        for count in (-1, True, 2):
            with self.subTest(count=count), self.assertRaises(ValueError):
                detector_view(call, count)

    def test_english_development_fixture_uses_same_projection(self):
        calls = json.loads((DATA_DIR / "dev_transcripts.json").read_text(encoding="utf-8"))
        view = detector_view(calls[0], 1)
        self.assertEqual(set(view), {"language", "segments"})
        self.assertEqual(set(view["segments"][0]), {"text", "start_at_ms", "end_at_ms"})
        self.assertNotIn(calls[0]["call_id"], json.dumps(view))
