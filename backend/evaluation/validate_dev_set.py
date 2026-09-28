"""Validate English dev transcripts without exposing ground truth as detector input."""

import argparse
import json
from pathlib import Path
import sys


TRANSCRIPT_FIELDS = {"call_id", "language", "segments"}
SEGMENT_FIELDS = {"segment_id", "start_at_ms", "end_at_ms", "speaker", "text", "final"}
TRUTH_FIELDS = {"call_id", "family_id", "label", "first_ask_at_ms"}


def _fields(record, expected, context):
    if not isinstance(record, dict):
        raise ValueError(f"{context} must be an object")
    missing = expected - record.keys()
    unexpected = record.keys() - expected
    if missing:
        raise ValueError(f"{context} is missing {', '.join(sorted(missing))}")
    if unexpected:
        raise ValueError(f"{context} has unexpected {', '.join(sorted(unexpected))}")


def _nonempty_string(value, context):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a nonempty string")


def _nonnegative_int(value, context):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a nonnegative integer")


def validate_dev_set(transcripts: list[dict], truth: list[dict], families: list[dict]) -> None:
    """Check structure, timing, lineage, and annotation alignment; never infer labels."""
    if not isinstance(transcripts, list) or len(transcripts) != 12:
        raise ValueError("expected exactly 12 transcripts")
    if not isinstance(truth, list) or len(truth) != 12:
        raise ValueError("expected exactly 12 ground-truth records")
    if not isinstance(families, list):
        raise ValueError("families must be a list")

    family_labels = {}
    for family in families:
        if not isinstance(family, dict) or "family_id" not in family or "label" not in family:
            raise ValueError("invalid family reference")
        if family["family_id"] in family_labels:
            raise ValueError(f"duplicate reference family_id: {family['family_id']}")
        family_labels[family["family_id"]] = family["label"]

    transcripts_by_id = {}
    for transcript in transcripts:
        _fields(transcript, TRANSCRIPT_FIELDS, "transcript")
        call_id = transcript["call_id"]
        _nonempty_string(call_id, "call_id")
        if call_id in transcripts_by_id:
            raise ValueError(f"duplicate transcript call_id: {call_id}")
        transcripts_by_id[call_id] = transcript
        if transcript["language"] != "en":
            raise ValueError(f"call {call_id} must have language en")

        segments = transcript["segments"]
        if not isinstance(segments, list) or len(segments) < 4:
            raise ValueError(f"call {call_id} needs at least four segments")
        seen_segment_ids = set()
        previous_end = 0
        speakers = set()
        for index, segment in enumerate(segments):
            context = f"call {call_id} segment {index}"
            _fields(segment, SEGMENT_FIELDS, context)
            segment_id = segment["segment_id"]
            _nonempty_string(segment_id, f"{context} segment_id")
            if segment_id in seen_segment_ids:
                raise ValueError(f"call {call_id} has duplicate segment_id: {segment_id}")
            seen_segment_ids.add(segment_id)
            if segment["final"] is not True:
                raise ValueError(f"{context} must be finalized")
            if segment["speaker"] not in ("caller", "listener"):
                raise ValueError(f"{context} has an invalid speaker")
            speakers.add(segment["speaker"])
            _nonempty_string(segment["text"], f"{context} text")
            start = segment["start_at_ms"]
            end = segment["end_at_ms"]
            _nonnegative_int(start, f"{context} start_at_ms")
            _nonnegative_int(end, f"{context} end_at_ms")
            if start < previous_end or end <= start:
                raise ValueError(f"{context} has overlapping or unordered timestamps")
            previous_end = end
        if speakers != {"caller", "listener"}:
            raise ValueError(f"call {call_id} needs caller and listener turns")

    truth_by_id = {}
    used_families = set()
    for record in truth:
        _fields(record, TRUTH_FIELDS, "ground truth")
        call_id = record["call_id"]
        _nonempty_string(call_id, "ground-truth call_id")
        if call_id in truth_by_id:
            raise ValueError(f"duplicate ground-truth call_id: {call_id}")
        truth_by_id[call_id] = record
        family_id = record["family_id"]
        _nonempty_string(family_id, f"call {call_id} family_id")
        if family_id not in family_labels:
            raise ValueError(f"call {call_id} has an unknown family_id: {family_id}")
        if family_id in used_families:
            raise ValueError(f"duplicate dev family_id: {family_id}")
        used_families.add(family_id)
        if record["label"] not in ("scam", "genuine"):
            raise ValueError(f"call {call_id} has an invalid label")
        if record["label"] != family_labels[family_id]:
            raise ValueError(f"call {call_id} label disagrees with family {family_id}")

    if transcripts_by_id.keys() != truth_by_id.keys():
        raise ValueError("transcript and ground-truth call IDs differ")

    for call_id, record in truth_by_id.items():
        ask = record["first_ask_at_ms"]
        if record["label"] == "genuine":
            if ask is not None:
                raise ValueError(f"genuine call {call_id} must have a null first ask")
            continue
        _nonnegative_int(ask, f"scam call {call_id} first_ask_at_ms")
        caller_starts = {
            segment["start_at_ms"]
            for segment in transcripts_by_id[call_id]["segments"]
            if segment["speaker"] == "caller"
        }
        if ask not in caller_starts:
            raise ValueError(f"scam call {call_id} first ask must start a caller segment")


def main() -> int:
    data_dir = Path(__file__).parent / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", type=Path, default=data_dir / "dev_transcripts.json")
    parser.add_argument("--truth", type=Path, default=data_dir / "dev_ground_truth.json")
    parser.add_argument("--families", type=Path, default=data_dir / "families.json")
    args = parser.parse_args()
    try:
        transcripts = json.loads(args.transcripts.read_text(encoding="utf-8"))
        truth = json.loads(args.truth.read_text(encoding="utf-8"))
        families = json.loads(args.families.read_text(encoding="utf-8"))
        validate_dev_set(transcripts, truth, families)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Invalid dev set: {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(transcripts)} English dev timelines and ground-truth records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
