"""Validate candidate multilingual development calls and separate ground truth."""

import json
from pathlib import Path
import sys

try:
    from .validate_dev_set import (
        SEGMENT_FIELDS, TRANSCRIPT_FIELDS, _fields, _nonempty_string, _nonnegative_int,
    )
except ImportError:  # Direct script invocation from the repository root.
    from validate_dev_set import (
        SEGMENT_FIELDS, TRANSCRIPT_FIELDS, _fields, _nonempty_string, _nonnegative_int,
    )


DATA_DIR = Path(__file__).parent / "data"
TRUTH_FIELDS = {"call_id", "family_id", "pair_group_id", "label", "first_ask_at_ms"}
LANGUAGES = {"hi-en", "te-en"}


def validate_pilot(transcripts, truth, families, english_transcripts, heldout_families):
    """Check structure and lineage; semantic and language review remains human work."""
    if not isinstance(transcripts, list) or len(transcripts) != 4:
        raise ValueError("expected four pilot transcripts")
    if not isinstance(truth, list) or len(truth) != 4:
        raise ValueError("expected four pilot ground-truth records")
    if not all(isinstance(items, list) for items in (families, english_transcripts, heldout_families)):
        raise ValueError("reference data must be lists")

    family_by_id = {family["family_id"]: family for family in families}
    heldout_ids = {family["family_id"] for family in heldout_families}
    heldout_pair_ids = {family["pair_group_id"] for family in heldout_families}
    english_ids = {call["call_id"] for call in english_transcripts}
    if len(family_by_id) != len(families):
        raise ValueError("duplicate development family ID")
    if set(family_by_id) & heldout_ids:
        raise ValueError("development and held-out family IDs overlap")
    if {family["pair_group_id"] for family in families} & heldout_pair_ids:
        raise ValueError("development and held-out pair-group IDs overlap")

    calls = {}
    for transcript in transcripts:
        _fields(transcript, TRANSCRIPT_FIELDS, "transcript")
        call_id = transcript["call_id"]
        _nonempty_string(call_id, "call_id")
        if call_id in calls or call_id in english_ids:
            raise ValueError(f"duplicate or reused call_id: {call_id}")
        calls[call_id] = transcript
        if transcript["language"] not in LANGUAGES:
            raise ValueError(f"call {call_id} has unsupported language")
        segments = transcript["segments"]
        if not isinstance(segments, list) or len(segments) < 4:
            raise ValueError(f"call {call_id} needs at least four segments")
        previous_end = 0
        segment_ids = set()
        speakers = set()
        for index, segment in enumerate(segments):
            context = f"call {call_id} segment {index}"
            _fields(segment, SEGMENT_FIELDS, context)
            _nonempty_string(segment["segment_id"], f"{context} segment_id")
            if segment["segment_id"] in segment_ids:
                raise ValueError(f"{context} has duplicate segment_id")
            segment_ids.add(segment["segment_id"])
            if segment["speaker"] not in {"caller", "listener"}:
                raise ValueError(f"{context} has invalid speaker")
            speakers.add(segment["speaker"])
            if segment["final"] is not True:
                raise ValueError(f"{context} must be finalized")
            _nonempty_string(segment["text"], f"{context} text")
            start, end = segment["start_at_ms"], segment["end_at_ms"]
            _nonnegative_int(start, f"{context} start_at_ms")
            _nonnegative_int(end, f"{context} end_at_ms")
            if start < previous_end or end <= start:
                raise ValueError(f"{context} has overlapping or unordered timestamps")
            previous_end = end
        if speakers != {"caller", "listener"}:
            raise ValueError(f"call {call_id} needs both speakers")

    truth_by_id = {}
    pair_labels = {}
    for record in truth:
        _fields(record, TRUTH_FIELDS, "ground truth")
        call_id = record["call_id"]
        _nonempty_string(call_id, "ground-truth call_id")
        if call_id in truth_by_id:
            raise ValueError(f"duplicate ground-truth call_id: {call_id}")
        truth_by_id[call_id] = record
        if call_id not in calls:
            continue  # ID mismatch reported below
        family_id = record["family_id"]
        _nonempty_string(family_id, f"call {call_id} family_id")
        if family_id not in family_by_id or family_id in heldout_ids:
            raise ValueError(f"call {call_id} references non-development family")
        family = family_by_id[family_id]
        if record["label"] != family["label"] or record["label"] not in {"scam", "genuine"}:
            raise ValueError(f"call {call_id} label disagrees with family")
        if record["pair_group_id"] != family["pair_group_id"]:
            raise ValueError(f"call {call_id} pair_group_id disagrees with family")
        key = (calls[call_id]["language"], record["pair_group_id"])
        labels = pair_labels.setdefault(key, set())
        if record["label"] in labels:
            raise ValueError(f"duplicate {record['label']} in pilot pair {key}")
        labels.add(record["label"])
        ask = record["first_ask_at_ms"]
        if record["label"] == "genuine":
            if ask is not None:
                raise ValueError(f"genuine call {call_id} must have null first ask")
        else:
            _nonnegative_int(ask, f"scam call {call_id} first_ask_at_ms")
            caller_starts = {segment["start_at_ms"] for segment in calls[call_id]["segments"]
                             if segment["speaker"] == "caller"}
            if ask not in caller_starts:
                raise ValueError(f"scam call {call_id} first ask must start a caller segment")

    if calls.keys() != truth_by_id.keys():
        raise ValueError("transcript and ground-truth call IDs differ")
    if set(pair_labels) != {("hi-en", "kyc-update-seed-01"),
                            ("te-en", "courier-parcel-seed-01")}:
        raise ValueError("pilot must cover the two selected development pairs")
    if any(labels != {"scam", "genuine"} for labels in pair_labels.values()):
        raise ValueError("each pilot pair needs one scam and one genuine call")


def main():
    try:
        def load(name):
            return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))

        validate_pilot(
            load("multilingual_pilot_transcripts.json"),
            load("multilingual_pilot_ground_truth.json"),
            load("families.json"),
            load("dev_transcripts.json"),
            load("heldout_family_outlines.json"),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"Invalid multilingual pilot: {error}", file=sys.stderr)
        return 1
    print("Validated four candidate multilingual development calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
