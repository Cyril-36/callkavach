"""Replay the multilingual development pilot through the configured live detector."""

import argparse
import asyncio
from datetime import datetime, timezone
import importlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

from backend.evaluation.replay_runner import load_pilot, run_development_set


PROVIDER_HTTP_TIMEOUT_S = 8.0


def detector_commit():
    root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%H", "--", "backend/spike/detector.py"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("cannot identify the detector commit") from error
    commit = result.stdout.strip()
    if not commit:
        raise RuntimeError("cannot identify the detector commit")
    return commit


def api_usage(calls):
    """Sum only usage attached to emitted detector events; unknown values stay null."""
    records = []
    for call in calls:
        seen_calls = set()
        for event in call["risk_events"]:
            sequence = event.get("calls")
            metadata = event.get("verifier")
            if not isinstance(metadata, dict) or sequence in seen_calls:
                continue
            seen_calls.add(sequence)
            records.append(metadata)

    def total(field):
        values = [record[field] for record in records
                  if isinstance(record.get(field), (int, float))
                  and not isinstance(record[field], bool)]
        return sum(values) if values else None

    return {"responses_with_metadata": len(records),
            "prompt_tokens": total("prompt_tokens"),
            "completion_tokens": total("completion_tokens"),
            "reported_cost_total": total("cost"),
            "reported_cost_unit": "provider-defined; not inferred by runner"}


def live_components():
    """Load the main implementer's detector only after it has been merged."""
    spike_dir = Path(__file__).resolve().parents[1] / "spike"
    if not (spike_dir / "detector.py").is_file():
        raise RuntimeError("the actual detector is not on this branch yet; wait for PR #10")
    sys.path.insert(0, str(spike_dir))
    detector = importlib.import_module("detector")
    config = importlib.import_module("verifier_config")
    verifier, unavailable = config.make_verifier(timeout_s=PROVIDER_HTTP_TIMEOUT_S)
    if verifier is None:
        raise RuntimeError(unavailable or "detector verifier is unavailable")
    prompt_version = importlib.import_module("gemini_verifier").PROMPT_VERSION
    return detector, verifier, prompt_version


async def run(output: Path, finalize_timeout_s: float):
    transcripts, truth = load_pilot()
    detector, verifier, prompt_version = live_components()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        commit = detector_commit()
        detector_timeout_s = inspect.signature(detector.SessionDetector).parameters["call_timeout_s"].default
        report = await run_development_set(transcripts, truth, verifier, detector,
                                           finalize_timeout_s=finalize_timeout_s)
    finally:
        await verifier.close()
    report["reproducibility"] = {
        "detector_commit": commit,
        "provider": verifier.provider,
        "model": verifier.model,
        "prompt_version": prompt_version,
        "run_started_at_utc": started_at,
        "run_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "timeouts_s": {"provider_http": PROVIDER_HTTP_TIMEOUT_S,
                       "detector_call": detector_timeout_s,
                       "finalize": finalize_timeout_s},
        "api_usage": api_usage(report["calls"]),
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="Save synthetic text replay results outside the repository")
    parser.add_argument("--finalize-timeout-s", type=float, default=30)
    args = parser.parse_args()
    try:
        report = asyncio.run(run(args.output, args.finalize_timeout_s))
    except (OSError, ImportError, RuntimeError, ValueError) as error:
        print(f"Development replay unavailable: {error}", file=sys.stderr)
        return 1
    print(f"Replayed {len(report['calls'])} development calls; "
          f"{report['failure_calls']} had detector failures. Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
