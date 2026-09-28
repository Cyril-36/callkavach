"""Metrics for labelled calls and their emitted red alerts."""

from math import isfinite
from statistics import median


REQUIRED_FIELDS = (
    "call_id",
    "label",
    "language",
    "first_ask_at_ms",
    "red_alert_at_ms",
)


def _validated_calls(calls: list[dict]) -> list[dict]:
    if not isinstance(calls, list):
        raise ValueError("calls must be a list")

    seen_ids = set()
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise ValueError(f"call {index} must be an object")
        for field in REQUIRED_FIELDS:
            if field not in call:
                raise ValueError(f"call {index} is missing {field}")

        call_id = call["call_id"]
        if not isinstance(call_id, str) or not call_id:
            raise ValueError(f"call {index} has an invalid call_id")
        if call_id in seen_ids:
            raise ValueError(f"duplicate call_id: {call_id}")
        seen_ids.add(call_id)

        if call["label"] not in ("scam", "genuine"):
            raise ValueError(f"call {call_id} has an invalid label")
        if not isinstance(call["language"], str) or not call["language"]:
            raise ValueError(f"call {call_id} has an invalid language")
        for field in ("first_ask_at_ms", "red_alert_at_ms"):
            value = call[field]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(f"call {call_id} has an invalid {field}")
    return calls


def _rate(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def _summarize(calls: list[dict]) -> dict:
    scams = [call for call in calls if call["label"] == "scam"]
    genuine = [call for call in calls if call["label"] == "genuine"]
    detected = [call for call in scams if call["red_alert_at_ms"] is not None]
    eligible_asks = [call for call in scams if call["first_ask_at_ms"] is not None]
    before_ask = sum(
        call["red_alert_at_ms"] is not None
        and call["red_alert_at_ms"] < call["first_ask_at_ms"]
        for call in eligible_asks
    )

    return {
        "scam_recall": _rate(len(detected), len(scams)),
        "false_alarm_rate": _rate(
            sum(call["red_alert_at_ms"] is not None for call in genuine),
            len(genuine),
        ),
        "warned_before_ask": _rate(before_ask, len(eligible_asks)),
        "median_time_to_alert_ms": (
            median(call["red_alert_at_ms"] for call in detected) if detected else None
        ),
        "detected_scams": len(detected),
        "missed_scams": len(scams) - len(detected),
        "scams_without_ask": len(scams) - len(eligible_asks),
    }


def summarize_calls(calls: list[dict]) -> dict:
    """Summarize emitted red alerts for labelled calls, overall and by language."""
    _validated_calls(calls)
    languages = dict.fromkeys(call["language"] for call in calls)
    return {
        "overall": _summarize(calls),
        "by_language": {
            language: _summarize(
                [call for call in calls if call["language"] == language]
            )
            for language in languages
        },
    }
