"""The replay runner must never give labels or future turns to detection."""

import asyncio
from dataclasses import dataclass
import unittest

from backend.spike import detector as actual_detector
from backend.evaluation.replay_runner import replay_call, run_development_set


class FakeModule:
    seen = []

    @dataclass
    class Segment:
        segment_id: str
        text: str
        received_ms: int

    class SessionDetector:
        def __init__(self, verifier, emit, *, clock):
            self.verifier, self.emit, self.clock = verifier, emit, clock
            self.tasks = []
            self.count = 0

        def add(self, segment):
            FakeModule.seen.append(segment)
            self.count += 1
            level = "red" if "request" in segment.text else (
                "amber" if "caution" in segment.text else "none")
            self.tasks.append(asyncio.create_task(self.emit({
                "type": "risk", "level": level,
                "emitted_at_ms": self.clock(), "analysed_through_ms": segment.received_ms,
                "analysis": "unavailable" if self.verifier in {"fail", "auth"} else "ok",
                "error": ("analysis failed: AICredits HTTP 401: Invalid API Key"
                          if self.verifier == "auth" else
                          "scripted provider failure" if self.verifier == "fail" else None),
                "latency_s": 0.002,
            })))

        def idle(self):
            return all(task.done() for task in self.tasks)

        def summary(self):
            return {"status": "incomplete" if self.verifier in {"fail", "auth"} else "complete",
                    "analysed_segments": self.count}

        async def close(self):
            await asyncio.gather(*self.tasks)


def call(call_id, text):
    return {"call_id": call_id, "language": "hi-en", "label": "ANSWER_NOT_FOR_DETECTOR",
            "segments": [
                {"segment_id": "raw-answer-id", "speaker": "caller", "text": "ordinary context",
                 "start_at_ms": 0, "end_at_ms": 1, "final": True},
                {"segment_id": "s2", "speaker": "listener", "text": text,
                 "start_at_ms": 2, "end_at_ms": 3, "final": True},
            ]}


class ReplayRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeModule.seen = []

    async def test_replay_emits_only_projected_prefix_segments(self):
        transcript = call("scam-kyc-answer-id", "request an OTP")
        result = await replay_call(transcript, "ok", FakeModule)
        self.assertEqual([segment.text for segment in FakeModule.seen],
                         ["ordinary context", "request an OTP"])
        self.assertEqual([segment.segment_id for segment in FakeModule.seen], ["seg1", "seg2"])
        self.assertTrue(all(set(vars(segment)) == {"segment_id", "text", "received_ms"}
                            for segment in FakeModule.seen))
        self.assertEqual(result["first_red_at_ms"], result["risk_events"][1]["emitted_at_ms"])
        self.assertEqual(result["median_verifier_latency_ms"], 2)
        self.assertEqual(result["failures"], [])

    async def test_ground_truth_joins_only_after_detection_and_reports_false_alarm(self):
        transcripts = [call("opaque-a", "request help"), call("opaque-b", "request a delivery code")]
        truth = [
            {"call_id": "opaque-a", "label": "scam", "first_ask_at_ms": 2},
            {"call_id": "opaque-b", "label": "genuine", "first_ask_at_ms": None},
        ]
        report = await run_development_set(transcripts, truth, "ok", FakeModule)
        self.assertEqual(report["metrics"]["overall"]["scam_recall"]["numerator"], 1)
        self.assertEqual(report["metrics"]["overall"]["false_alarm_rate"]["numerator"], 1)
        self.assertEqual(report["failure_calls"], 0)
        self.assertEqual(report["language_review"], {
            "hi-en": "independent_fluent_review_pending",
            "te-en": "independent_fluent_review_pending",
        })
        self.assertIn("provisional", report["score_status"])
        self.assertEqual(report["latency"]["verifier_calls"], 4)
        self.assertEqual(report["latency"]["median_verifier_latency_ms"], 2)
        self.assertEqual(len(FakeModule.seen), 4)
        self.assertTrue(all("opaque" not in segment.text for segment in FakeModule.seen))

    async def test_failure_is_reported_and_missing_ids_rejected(self):
        result = await replay_call(call("opaque", "ordinary end"), "fail", FakeModule)
        self.assertIsNone(result["first_red_at_ms"])
        self.assertIn("scripted provider failure", result["failures"])
        self.assertIn("detector summary is incomplete", result["failures"])
        with self.assertRaisesRegex(ValueError, "call IDs differ"):
            await run_development_set([call("a", "hello")],
                                      [{"call_id": "b", "label": "scam", "first_ask_at_ms": 0}],
                                      "ok", FakeModule)
        previous_count = len(FakeModule.seen)
        with self.assertRaisesRegex(ValueError, "invalid label"):
            await run_development_set([call("a", "hello")],
                                      [{"call_id": "a", "label": "unknown", "first_ask_at_ms": 0}],
                                      "ok", FakeModule)
        self.assertEqual(len(FakeModule.seen), previous_count)

    async def test_amber_is_separate_and_failed_calls_stay_in_denominators(self):
        transcripts = [call("genuine", "caution about OTP"),
                       call("scam", "ordinary end")]
        truth = [{"call_id": "genuine", "label": "genuine", "first_ask_at_ms": None},
                 {"call_id": "scam", "label": "scam", "first_ask_at_ms": 2}]
        report = await run_development_set(transcripts, truth, "fail", FakeModule)
        overall = report["metrics"]["overall"]
        self.assertEqual(overall["false_alarm_rate"],
                         {"numerator": 0, "denominator": 1, "rate": 0.0})
        self.assertEqual(overall["scam_recall"],
                         {"numerator": 0, "denominator": 1, "rate": 0.0})
        self.assertEqual(report["amber_warning_rates"]["overall"]["genuine_amber_warning_rate"],
                         {"numerator": 1, "denominator": 1, "rate": 1.0})
        self.assertEqual(report["failure_calls"], 2)
        self.assertIn("RED", report["metric_definitions"]["false_alarm_rate"])

    async def test_invalid_api_key_stops_before_replaying_remaining_calls(self):
        transcripts = [call("first", "ordinary end"), call("second", "ordinary end")]
        truth = [{"call_id": name, "label": "genuine", "first_ask_at_ms": None}
                 for name in ("first", "second")]
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            await run_development_set(transcripts, truth, "auth", FakeModule)
        self.assertEqual(len(FakeModule.seen), 1)

    async def test_merged_detector_contract_with_fake_verifier(self):
        class Verifier:
            last_call = None

            async def analyse(self, request):
                segment = request["segments"][-1]
                return [{"tactic": "credential_request", "status": "present",
                         "segment_id": segment["segment_id"], "quote": segment["text"]}]

        transcript = {"call_id": "opaque-only-for-report", "language": "hi-en", "segments": [
            {"segment_id": "raw-answer-id", "speaker": "caller",
             "text": "Read the banking OTP to me.", "start_at_ms": 0, "end_at_ms": 1,
             "final": True},
        ]}
        result = await replay_call(transcript, Verifier(), actual_detector)
        self.assertEqual(result["detector_summary"]["level"], "red")
        self.assertEqual(result["first_red_at_ms"], result["risk_events"][0]["emitted_at_ms"])
        self.assertEqual(result["risk_events"][0]["tactics"][0]["evidence"][0]["segment_id"],
                         "seg1")
        self.assertEqual(result["failures"], [])
