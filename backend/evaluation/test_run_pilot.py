"""Reproducibility metadata must report returned usage without inventing costs."""

import re
import subprocess
import unittest
from unittest.mock import patch

from backend.evaluation.run_pilot import api_usage, detector_commit, repo_state


class RunPilotMetadataTests(unittest.TestCase):
    def test_detector_commit_is_a_full_sha(self):
        self.assertRegex(detector_commit(), re.compile(r"^[0-9a-f]{40}$"))

    def test_repo_state_records_commit_and_uncommitted_files(self):
        sha = "a" * 40
        with patch("backend.evaluation.run_pilot.subprocess.run", side_effect=[
            subprocess.CompletedProcess([], 0, sha + "\n", ""),
            subprocess.CompletedProcess([], 0, " M backend/evaluation/run_pilot.py\n", ""),
        ]):
            self.assertEqual(repo_state(), {"repo_commit": sha, "uncommitted_changes": True})
        with patch("backend.evaluation.run_pilot.subprocess.run", side_effect=[
            subprocess.CompletedProcess([], 0, sha + "\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]):
            self.assertFalse(repo_state()["uncommitted_changes"])

    def test_api_usage_counts_reported_values_only(self):
        calls = [{"detector_summary": {"calls": 4}, "risk_events": [
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
        self.assertEqual(api_usage(calls)["detector_requests"], 4)
        self.assertEqual(api_usage(calls)["responses_with_reported_cost"], 2)
        self.assertEqual(api_usage(calls)["prompt_tokens"], 27)
        self.assertEqual(api_usage(calls)["completion_tokens"], 4)
        self.assertEqual(api_usage(calls)["reported_cost_total"], 0.04)
        self.assertTrue(api_usage(calls)["reported_cost_is_partial"])
        self.assertIsNone(api_usage([{"detector_summary": {"calls": 1},
                                      "risk_events": []}])["reported_cost_total"])
        self.assertTrue(api_usage([{"detector_summary": {"calls": 1},
                                    "risk_events": []}])["reported_cost_is_partial"])
        self.assertFalse(api_usage([{"detector_summary": {"calls": 1},
                                     "risk_events": [calls[0]["risk_events"][0]]}])
                         ["reported_cost_is_partial"])
