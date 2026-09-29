"""Reproducibility metadata must report returned usage without inventing costs."""

import re
import unittest

from backend.evaluation.run_pilot import api_usage, detector_commit


class RunPilotMetadataTests(unittest.TestCase):
    def test_detector_commit_is_a_full_sha(self):
        self.assertRegex(detector_commit(), re.compile(r"^[0-9a-f]{40}$"))

    def test_api_usage_counts_reported_values_only(self):
        calls = [{"risk_events": [
            {"calls": 1, "analysis": "ok", "verifier": {"prompt_tokens": 10,
                                                "completion_tokens": 4, "cost": 0.02}},
            {"calls": 2, "analysis": "ok", "verifier": {"prompt_tokens": 7,
                                                "completion_tokens": None, "cost": None}},
            {"calls": 3, "analysis": "unavailable", "verifier": {"prompt_tokens": 10,
                                                         "cost": 0.02}},
            {"calls": 3, "analysis": "unavailable", "verifier": {"prompt_tokens": 10,
                                                         "cost": 0.02}},
        ]}]
        self.assertEqual(api_usage(calls)["responses_with_metadata"], 3)
        self.assertEqual(api_usage(calls)["prompt_tokens"], 27)
        self.assertEqual(api_usage(calls)["completion_tokens"], 4)
        self.assertEqual(api_usage(calls)["reported_cost_total"], 0.04)
        self.assertIsNone(api_usage([{"risk_events": []}])["reported_cost_total"])
