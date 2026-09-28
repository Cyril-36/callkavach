"""Tests for the scenario-family structure and pair counts."""

from copy import deepcopy
import unittest

from backend.evaluation.validate_families import validate_families


SCENARIOS = (
    "digital-arrest",
    "courier-parcel",
    "kyc-update",
    "bank-card-block",
    "trai-sim-disconnection",
    "electricity-bill",
)


def valid_families():
    families = []
    for scenario in SCENARIOS:
        for label in ("scam", "genuine"):
            families.append({
                "family_id": f"{scenario}-{label}",
                "label": label,
                "scenario_type": scenario,
                "steps": [
                    {"caller_intent": "Introduce the topic", "example_line": "Hello."},
                    {"caller_intent": "Explain the issue", "example_line": "Please listen."},
                    {"caller_intent": "Close the call", "example_line": "Goodbye."},
                ],
                "first_dangerous_ask_step": 2 if label == "scam" else None,
            })
    return families


class ValidateFamiliesTests(unittest.TestCase):
    def test_valid_twelve_family_structure(self):
        families = valid_families()
        original = deepcopy(families)
        self.assertIsNone(validate_families(families))
        self.assertEqual(families, original)

    def test_rejects_duplicate_ids_and_pair_counts(self):
        families = valid_families()
        families[1]["family_id"] = families[0]["family_id"]
        with self.assertRaisesRegex(ValueError, "duplicate family_id"):
            validate_families(families)

        families = valid_families()
        families[1]["scenario_type"] = "kyc-update"
        with self.assertRaisesRegex(ValueError, "expected one genuine family"):
            validate_families(families)

    def test_rejects_missing_fields_bad_labels_and_types(self):
        for field in ("family_id", "label", "scenario_type", "steps", "first_dangerous_ask_step"):
            families = valid_families()
            del families[0][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "missing"):
                validate_families(families)

        for field, value, message in (
            ("label", "unknown", "invalid label"),
            ("scenario_type", "unknown", "invalid scenario_type"),
        ):
            families = valid_families()
            families[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                validate_families(families)

    def test_rejects_step_lengths_and_empty_step_fields(self):
        for steps in ([], valid_families()[0]["steps"] * 3):
            families = valid_families()
            families[0]["steps"] = steps
            with self.subTest(length=len(steps)), self.assertRaisesRegex(ValueError, "3 to 6"):
                validate_families(families)

        families = valid_families()
        families[0]["steps"][0]["example_line"] = " "
        with self.assertRaisesRegex(ValueError, "empty example_line"):
            validate_families(families)

    def test_rejects_invalid_ask_indices(self):
        for ask_step in (None, -1, 3, True):
            families = valid_families()
            families[0]["first_dangerous_ask_step"] = ask_step
            with self.subTest(ask_step=ask_step), self.assertRaisesRegex(ValueError, "invalid ask step"):
                validate_families(families)

        families = valid_families()
        families[1]["first_dangerous_ask_step"] = 0
        with self.assertRaisesRegex(ValueError, "null ask step"):
            validate_families(families)


if __name__ == "__main__":
    unittest.main()
