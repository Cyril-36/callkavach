"""Project a development fixture into one safe incremental detector prefix."""


def detector_view(transcript: dict, finalized_count: int) -> dict:
    """Return only language and the first N finalized text/timing segments.

    The caller controls the replay boundary. Call once per newly finalized turn;
    never hand the raw evaluation fixture to a detector or Gemini.
    """
    if isinstance(finalized_count, bool) or not isinstance(finalized_count, int) or finalized_count < 0:
        raise ValueError("finalized_count must be a nonnegative integer")
    finalized = [segment for segment in transcript["segments"] if segment["final"] is True]
    if finalized_count > len(finalized):
        raise ValueError("finalized_count exceeds available finalized segments")
    return {
        "language": transcript["language"],
        "segments": [
            {
                "text": segment["text"],
                "start_at_ms": segment["start_at_ms"],
                "end_at_ms": segment["end_at_ms"],
            }
            for segment in finalized[:finalized_count]
        ],
    }
