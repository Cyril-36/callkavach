"""A deliberately simple lexical baseline over unfolding transcripts."""

from __future__ import annotations


def first_keyword_alert(segments: list[dict], phrases: list[str]) -> int | None:
    """Return the end time of the first matching, finalized segment."""
    if not isinstance(segments, list) or not isinstance(phrases, list):
        raise ValueError("segments and phrases must be lists")
    if any(not isinstance(phrase, str) or not phrase.strip() for phrase in phrases):
        raise ValueError("phrases must contain nonempty strings")

    folded_phrases = [phrase.casefold() for phrase in phrases]
    seen_final_ids = set()
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"segment {index} must be an object")
        for field in ("segment_id", "end_at_ms", "text", "final"):
            if field not in segment:
                raise ValueError(f"segment {index} is missing {field}")
        if not isinstance(segment["final"], bool):
            raise ValueError(f"segment {index} has an invalid final flag")
        if not segment["final"]:
            continue

        segment_id = segment["segment_id"]
        if not isinstance(segment_id, str) or not segment_id:
            raise ValueError(f"segment {index} has an invalid segment_id")
        if segment_id in seen_final_ids:
            continue
        seen_final_ids.add(segment_id)

        end_at_ms = segment["end_at_ms"]
        if isinstance(end_at_ms, bool) or not isinstance(end_at_ms, int) or end_at_ms < 0:
            raise ValueError(f"segment {index} has an invalid end_at_ms")
        if not isinstance(segment["text"], str):
            raise ValueError(f"segment {index} has an invalid text")

        text = segment["text"].casefold()
        if any(phrase in text for phrase in folded_phrases):
            return end_at_ms
    return None
