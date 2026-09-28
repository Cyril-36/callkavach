"""Tests for development/held-out pair integrity and separation."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.evaluation.validate_heldout_families import validate_heldout_families


DATA_DIR = Path(__file__).parent / "data"


def family_sets():
    heldout = json.loads((DATA_DIR / "heldout_family_outlines.json").read_text(encoding="utf-8"))
    dev = json.loads((DATA_DIR / "families.json").read_text(encoding="utf-8"))
    return heldout, dev


class ValidateHeldoutFamiliesTests(unittest.TestCase):
    def test_repository_pairs_are_valid_without_mutation(self):
        heldout, dev = family_sets()
        original = deepcopy((heldout, dev))
        self.assertIsNone(validate_heldout_families(heldout, dev))
        self.assertEqual((heldout, dev), original)

    def test_rejects_missing_group_id(self):
        heldout, dev = family_sets()
        del heldout[0]["pair_group_id"]
        with self.assertRaisesRegex(ValueError, "invalid pair_group_id"):
            validate_heldout_families(heldout, dev)

    def test_rejects_split_or_mislabelled_pairs(self):
        heldout, dev = family_sets()
        heldout[0]["pair_group_id"] = "unpaired-group"
        with self.assertRaisesRegex(ValueError, "one scam and one genuine"):
            validate_heldout_families(heldout, dev)

        heldout, dev = family_sets()
        heldout[1]["pair_group_id"], heldout[2]["pair_group_id"] = (
            heldout[2]["pair_group_id"], heldout[1]["pair_group_id"]
        )
        with self.assertRaisesRegex(ValueError, "one scam and one genuine"):
            validate_heldout_families(heldout, dev)

    def test_rejects_mixed_scenario_group(self):
        heldout, dev = family_sets()
        heldout[0]["pair_group_id"], heldout[2]["pair_group_id"] = (
            heldout[2]["pair_group_id"], heldout[0]["pair_group_id"]
        )
        with self.assertRaisesRegex(ValueError, "mixes scenario types"):
            validate_heldout_families(heldout, dev)

    def test_rejects_dev_heldout_id_overlap(self):
        heldout, dev = family_sets()
        heldout[0]["family_id"] = dev[0]["family_id"]
        with self.assertRaisesRegex(ValueError, "family_id overlap"):
            validate_heldout_families(heldout, dev)

        heldout, dev = family_sets()
        for family in heldout[:2]:
            family["pair_group_id"] = dev[0]["pair_group_id"]
        with self.assertRaisesRegex(ValueError, "pair_group_id overlap"):
            validate_heldout_families(heldout, dev)


if __name__ == "__main__":
    unittest.main()
