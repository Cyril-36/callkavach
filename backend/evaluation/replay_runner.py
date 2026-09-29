"""Replay development text through the live detector and join truth afterward.

This module has no provider dependency at import time. The detector and verifier
are supplied by the caller; the CLI loads the merged backend/spike implementation.
"""

import asyncio
import json
from pathlib import Path
from statistics import median

from backend.evaluation.detector_view import detector_view
from backend.evaluation.metrics import summarize_calls
from backend.evaluation.validate_multilingual_pilot import validate_pilot


DATA_DIR = Path(__file__).parent / "data"


def _fatal_provider_error(event):
    error = str(event.get("error") or "")
    if "AICredits HTTP 401" in error:
        return "AICredits rejected the API key (HTTP 401)"
    if "Gemini HTTP 429" in error and "exceeded your current quota" in error.lower():
        return "Gemini quota exhausted (HTTP 429)"
    return None


def _rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def _amber_warning_summary(results, truth):
    """Count emitted amber warnings independently of red alerts, including failed calls."""
    by_id = {record["call_id"]: record for record in truth}

    def summarize(calls):
        genuine = [call for call in calls if by_id[call["call_id"]]["label"] == "genuine"]
        scams = [call for call in calls if by_id[call["call_id"]]["label"] == "scam"]
        warned = lambda call: any(event.get("level") == "amber" for event in call["risk_events"])
        return {
            "genuine_amber_warning_rate": _rate(sum(map(warned, genuine)), len(genuine)),
            "scam_amber_warning_rate": _rate(sum(map(warned, scams)), len(scams)),
        }

    languages = dict.fromkeys(call["language"] for call in results)
    return {"overall": summarize(results), "by_language": {
        language: summarize([call for call in results if call["language"] == language])
        for language in languages
    }}


async def replay_call(transcript, verifier, detector_module, *, finalize_timeout_s=30):
    """Feed one finalized segment at each scripted end time, capturing real risk events.

    The transcript's synthetic timing controls playback. Risk emission and
    receive times come from the event loop's monotonic clock, not annotations.
    Neither call ID nor ground truth enters the detector.
    """
    if finalize_timeout_s <= 0:
        raise ValueError("finalize_timeout_s must be positive")
    loop = asyncio.get_running_loop()
    started = loop.time()
    clock_ms = lambda: int((loop.time() - started) * 1000)
    events = []
    received = []
    fatal_provider_failure = False

    async def emit(event):
        nonlocal fatal_provider_failure
        if event.get("type") == "risk":
            events.append(event)
            if _fatal_provider_error(event):
                fatal_provider_failure = True

    detector = detector_module.SessionDetector(verifier, emit, clock=clock_ms)
    timed_out = False
    try:
        for count in range(1, len(transcript["segments"]) + 1):
            segment = detector_view(transcript, count)["segments"][-1]
            target_s = segment["end_at_ms"] / 1000
            await asyncio.sleep(max(0, target_s - (loop.time() - started)))
            if fatal_provider_failure:
                break
            at_ms = clock_ms()
            received.append(at_ms)
            detector.add(detector_module.Segment(
                segment_id=f"seg{count}", text=segment["text"], received_ms=at_ms,
            ))
        deadline = loop.time() + finalize_timeout_s
        while not detector.idle():
            if loop.time() >= deadline:
                timed_out = True
                break
            await asyncio.sleep(min(0.05, max(0, deadline - loop.time())))
        summary = detector.summary()
    finally:
        await detector.close()

    first_red = next((event.get("emitted_at_ms") for event in events
                      if event.get("level") == "red"), None)
    first_warning = next((event.get("emitted_at_ms") for event in events
                          if event.get("level") in {"amber", "red"}), None)
    failures = []
    if timed_out:
        failures.append("detector did not settle before the finalize deadline")
    if not events:
        failures.append("detector emitted no risk events")
    for event in events:
        if event.get("analysis") in {"unavailable", "partial"}:
            failures.append(event.get("error") or f"analysis {event['analysis']}")
        if event.get("level") == "red" and event.get("emitted_at_ms") is None:
            failures.append("red risk event lacks an emission timestamp")
    if summary.get("status") != "complete":
        failures.append(f"detector summary is {summary.get('status', 'missing')}")

    latencies = [round(event["latency_s"] * 1000)
                 for event in events if isinstance(event.get("latency_s"), (int, float))]
    delays = [event["emitted_at_ms"] - event["analysed_through_ms"]
              for event in events if event.get("analysis") in {"ok", "partial"}
              and isinstance(event.get("emitted_at_ms"), (int, float))
              and isinstance(event.get("analysed_through_ms"), (int, float))]
    return {
        "call_id": transcript["call_id"],  # Added only after the detector has closed.
        "language": transcript["language"],
        "timing_basis": "synthetic_text_replay_with_real_detector_clock",
        "risk_events": events,
        "received_at_ms": received,
        "first_warning_at_ms": first_warning,
        "first_red_at_ms": first_red,
        "median_verifier_latency_ms": median(latencies) if latencies else None,
        "median_post_receive_delay_ms": median(delays) if delays else None,
        "detector_summary": summary,
        "failures": list(dict.fromkeys(failures)),
    }


async def run_development_set(transcripts, truth, verifier, detector_module, *, finalize_timeout_s=30):
    """Replay the development calls serially; join labels only after each run."""
    by_id = {record["call_id"]: record for record in truth}
    call_ids = [call["call_id"] for call in transcripts]
    if len(by_id) != len(truth) or len(set(call_ids)) != len(call_ids) or set(call_ids) != by_id.keys():
        raise ValueError("transcript and ground-truth call IDs differ")
    # Fail on malformed truth before any paid detector calls. It is never fed to detection.
    metric_inputs = [
        {"call_id": call["call_id"], "language": call["language"],
         "label": by_id[call["call_id"]]["label"],
         "first_ask_at_ms": by_id[call["call_id"]]["first_ask_at_ms"],
         "red_alert_at_ms": None}
        for call in transcripts
    ]
    summarize_calls(metric_inputs)
    results = []
    for index, transcript in enumerate(transcripts):
        result = await replay_call(transcript, verifier, detector_module,
                                   finalize_timeout_s=finalize_timeout_s)
        fatal_error = next(filter(None, (_fatal_provider_error(event)
                                         for event in result["risk_events"])), None)
        if fatal_error:
            raise RuntimeError(f"{fatal_error}; stopped the pilot replay")
        results.append(result)
        metric_inputs[index]["red_alert_at_ms"] = result["first_red_at_ms"]
    event_latencies = [round(event["latency_s"] * 1000) for result in results
                       for event in result["risk_events"]
                       if isinstance(event.get("latency_s"), (int, float))]
    event_delays = [event["emitted_at_ms"] - event["analysed_through_ms"]
                    for result in results for event in result["risk_events"]
                    if event.get("analysis") in {"ok", "partial"}
                    and isinstance(event.get("emitted_at_ms"), (int, float))
                    and isinstance(event.get("analysed_through_ms"), (int, float))]
    return {
        "dataset": "multilingual_development_pilot",
        "timing_basis": "synthetic_text_replay_with_real_detector_clock",
        "review_status": "independent_language_review_pending",
        "language_review": {"hi-en": "independent_fluent_review_pending",
                            "te-en": "independent_fluent_review_pending"},
        "score_status": "provisional_pending_independent_fluent_review",
        "calls": results,
        "metrics": summarize_calls(metric_inputs),
        "metric_definitions": {
            "false_alarm_rate": "genuine calls with an emitted RED alert / all genuine calls",
            "amber_warning_rates": "calls with an emitted AMBER event / all calls of that label; may also later turn RED",
            "failed_sessions": "included in all applicable rate denominators",
        },
        "amber_warning_rates": _amber_warning_summary(results, truth),
        "latency": {
            "verifier_calls": len(event_latencies),
            "median_verifier_latency_ms": median(event_latencies) if event_latencies else None,
            "post_receive_samples": len(event_delays),
            "median_post_receive_delay_ms": median(event_delays) if event_delays else None,
        },
        "failure_calls": sum(bool(result["failures"]) for result in results),
    }


def load_pilot():
    """Load only the development pilot and validate its separation and lineage."""
    def load(name):
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))

    transcripts = load("multilingual_pilot_transcripts.json")
    truth = load("multilingual_pilot_ground_truth.json")
    validate_pilot(transcripts, truth, load("families.json"), load("dev_transcripts.json"),
                   load("heldout_family_outlines.json"))
    return transcripts, truth
