"""Replay the multilingual development pilot through the configured live detector."""

import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys

from backend.evaluation.replay_runner import load_pilot, run_development_set


def live_components():
    """Load the main implementer's detector only after it has been merged."""
    spike_dir = Path(__file__).resolve().parents[1] / "spike"
    if not (spike_dir / "detector.py").is_file():
        raise RuntimeError("the actual detector is not on this branch yet; wait for PR #10")
    sys.path.insert(0, str(spike_dir))
    detector = importlib.import_module("detector")
    config = importlib.import_module("verifier_config")
    verifier, unavailable = config.make_verifier()
    if verifier is None:
        raise RuntimeError(unavailable or "detector verifier is unavailable")
    return detector, verifier


async def run(output: Path, finalize_timeout_s: float):
    transcripts, truth = load_pilot()
    detector, verifier = live_components()
    try:
        report = await run_development_set(transcripts, truth, verifier, detector,
                                           finalize_timeout_s=finalize_timeout_s)
    finally:
        await verifier.close()
    report["detector"] = {"provider": verifier.provider, "model": verifier.model}
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
