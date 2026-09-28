"""Validate proposed held-out pair groups against development families."""

import json
from pathlib import Path
import sys

if __package__:
    from .validate_families import validate_families
else:
    from validate_families import validate_families


def _groups(families: list[dict], set_name: str) -> dict[str, list[dict]]:
    groups = {}
    for family in families:
        group_id = family.get("pair_group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError(f"{set_name} family {family['family_id']} has an invalid pair_group_id")
        groups.setdefault(group_id, []).append(family)

    for group_id, members in groups.items():
        if len(members) != 2 or {member["label"] for member in members} != {"scam", "genuine"}:
            raise ValueError(f"{set_name} pair group {group_id} must have one scam and one genuine family")
        if len({member["scenario_type"] for member in members}) != 1:
            raise ValueError(f"{set_name} pair group {group_id} mixes scenario types")
    if len(groups) != 6:
        raise ValueError(f"{set_name} must have exactly six pair groups")
    return groups


def validate_heldout_families(heldout: list[dict], dev: list[dict]) -> None:
    """Check structure, intact pairs, and ID separation; content still needs human review."""
    validate_families(dev)
    validate_families(heldout)
    dev_groups = _groups(dev, "development")
    heldout_groups = _groups(heldout, "held-out")

    overlapping_ids = {family["family_id"] for family in dev} & {
        family["family_id"] for family in heldout
    }
    if overlapping_ids:
        raise ValueError(f"development/held-out family_id overlap: {sorted(overlapping_ids)}")
    overlapping_groups = dev_groups.keys() & heldout_groups.keys()
    if overlapping_groups:
        raise ValueError(f"development/held-out pair_group_id overlap: {sorted(overlapping_groups)}")


def main() -> int:
    data_dir = Path(__file__).parent / "data"
    try:
        heldout = json.loads((data_dir / "heldout_family_outlines.json").read_text(encoding="utf-8"))
        dev = json.loads((data_dir / "families.json").read_text(encoding="utf-8"))
        validate_heldout_families(heldout, dev)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Invalid held-out families: {error}", file=sys.stderr)
        return 1
    print("Validated six proposed held-out pairs against six development pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
