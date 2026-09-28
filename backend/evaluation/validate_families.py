"""Validate the synthetic scenario-family seeds used for later evaluation."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


SCENARIO_TYPES = (
    "digital-arrest",
    "courier-parcel",
    "kyc-update",
    "bank-card-block",
    "trai-sim-disconnection",
    "electricity-bill",
)
LABELS = ("scam", "genuine")
REQUIRED_FAMILY_FIELDS = (
    "family_id",
    "label",
    "scenario_type",
    "steps",
    "first_dangerous_ask_step",
)


def validate_families(families: list[dict]) -> None:
    """Raise ValueError when the collection violates issue #2's structure."""
    if not isinstance(families, list) or len(families) != 12:
        raise ValueError("expected exactly 12 families")

    seen_ids = set()
    counts = Counter()
    for position, family in enumerate(families):
        if not isinstance(family, dict):
            raise ValueError(f"family {position} must be an object")
        for field in REQUIRED_FAMILY_FIELDS:
            if field not in family:
                raise ValueError(f"family {position} is missing {field}")

        family_id = family["family_id"]
        if not isinstance(family_id, str) or not family_id.strip():
            raise ValueError(f"family {position} has an invalid family_id")
        if family_id in seen_ids:
            raise ValueError(f"duplicate family_id: {family_id}")
        seen_ids.add(family_id)

        label = family["label"]
        scenario_type = family["scenario_type"]
        if label not in LABELS:
            raise ValueError(f"family {family_id} has an invalid label")
        if scenario_type not in SCENARIO_TYPES:
            raise ValueError(f"family {family_id} has an invalid scenario_type")
        counts[(scenario_type, label)] += 1

        steps = family["steps"]
        if not isinstance(steps, list) or not 3 <= len(steps) <= 6:
            raise ValueError(f"family {family_id} must have 3 to 6 steps")
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"family {family_id} step {index} must be an object")
            for field in ("caller_intent", "example_line"):
                if field not in step:
                    raise ValueError(f"family {family_id} step {index} is missing {field}")
                if not isinstance(step[field], str) or not step[field].strip():
                    raise ValueError(f"family {family_id} step {index} has an empty {field}")

        ask_step = family["first_dangerous_ask_step"]
        if label == "genuine" and ask_step is not None:
            raise ValueError(f"genuine family {family_id} must have a null ask step")
        if label == "scam" and (
            isinstance(ask_step, bool)
            or not isinstance(ask_step, int)
            or not 0 <= ask_step < len(steps)
        ):
            raise ValueError(f"scam family {family_id} has an invalid ask step")

    for scenario_type in SCENARIO_TYPES:
        for label in LABELS:
            if counts[(scenario_type, label)] != 1:
                raise ValueError(
                    f"expected one {label} family for {scenario_type}; "
                    f"found {counts[(scenario_type, label)]}"
                )


def main() -> int:
    default_path = Path(__file__).parent / "data" / "families.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=default_path)
    args = parser.parse_args()
    try:
        families = json.loads(args.path.read_text(encoding="utf-8"))
        validate_families(families)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Invalid families: {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(families)} families in {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
