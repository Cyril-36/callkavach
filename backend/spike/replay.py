"""Sequential text replay of one call through SessionDetector: a functional check, NOT a timing benchmark.

Input is exactly the output of backend/evaluation/detector_view.py (all finalized segments of a call):
  {"language": str, "segments": [{"text": str, "start_at_ms": int, "end_at_ms": int}, ...]}
Any other key is rejected, so labels, family IDs, speaker labels and first-ask times cannot reach the
detector. Segments get opaque IDs r1, r2, ... in order.

What it is for: whether the production detector (same timeout, validation and risk policy) reaches a
warning level on a call's text, with which evidence, and whether analysis completed. It is NOT valid for
live timing or warned-before-first-ask metrics: it waits for each analysis to finish before feeding the next
segment, so it never models analysis backlog, coalescing, or segments arriving while a call is in flight,
and it has no Stop deadline. Time-based development metrics belong to the evaluation runner (PR #11), which
schedules segments on a real monotonic timeline; live Stop behaviour is measured by e2e_harness.py.

Clock ("sequential_replay"): segment i is received at max(its scripted end_at_ms, the virtual time when the
previous analysis finished), and the clock then advances by real elapsed processing time. Virtual time
never runs backwards: when an earlier analysis finishes after a later segment's scripted end, that segment
is received late, and the result records both its scripted end and its effective receive time.

The result format is documented in DETECTOR_CONTRACT.md (schema callkavach.detector_replay.v1).
"""
import asyncio

from detector import Segment, SessionDetector

SCHEMA = "callkavach.detector_replay.v1"
_TOP = {"language", "segments"}
_SEGMENT = {"text", "start_at_ms", "end_at_ms"}


def _check(view: dict) -> None:
    if not isinstance(view, dict) or set(view) != _TOP:
        raise ValueError(f"replay input must have exactly {sorted(_TOP)}; got {sorted(view) if isinstance(view, dict) else type(view)}")
    last_end = -1
    for i, s in enumerate(view["segments"]):
        if not isinstance(s, dict) or set(s) != _SEGMENT:
            raise ValueError(f"segment {i} must have exactly {sorted(_SEGMENT)}")
        if not isinstance(s["text"], str) or not all(isinstance(s[k], int) and not isinstance(s[k], bool)
                                                      for k in ("start_at_ms", "end_at_ms")):
            raise ValueError(f"segment {i} has a wrongly typed field")
        if s["end_at_ms"] < s["start_at_ms"] or s["end_at_ms"] < last_end:
            raise ValueError(f"segment {i} is out of order")
        last_end = s["end_at_ms"]


async def replay_text_call(view: dict, verifier, *, call_timeout_s: float = 8.0, idle_timeout_s: float = 60.0) -> dict:
    _check(view)
    loop = asyncio.get_running_loop()
    clock_state = {"base_ms": 0, "fed_at": loop.time()}
    events = []
    timeline = []

    def clock() -> int:
        return int(clock_state["base_ms"] + (loop.time() - clock_state["fed_at"]) * 1000)

    async def emit(event):
        events.append(event)

    detector = SessionDetector(verifier, emit, clock=clock, call_timeout_s=call_timeout_s, min_interval_s=0.0)
    try:
        for i, s in enumerate(view["segments"]):
            # Never earlier than "now": a slow previous analysis delays this segment instead of rewinding time.
            received_ms = max(s["end_at_ms"], clock())
            clock_state["base_ms"], clock_state["fed_at"] = received_ms, loop.time()
            timeline.append({"replay_id": f"r{i + 1}", "scripted_end_at_ms": s["end_at_ms"],
                             "effective_receive_ms": received_ms, "delayed_by_ms": received_ms - s["end_at_ms"]})
            detector.add(Segment(f"r{i + 1}", s["text"], received_ms))
            deadline = loop.time() + idle_timeout_s
            while not detector.idle():
                if loop.time() > deadline:
                    raise TimeoutError(f"detector did not become idle within {idle_timeout_s:g} s")
                await asyncio.sleep(0.01)
        summary = detector.summary()
    finally:
        await detector.close()
    costs = [e["verifier"]["cost"] for e in events if e.get("verifier") and e["verifier"].get("cost") is not None]
    return {
        "schema": SCHEMA,
        "clock": "sequential_replay",
        "valid_for_live_timing_metrics": False,
        "language": view["language"],
        "segment_count": len(view["segments"]),
        "config": {"provider": getattr(verifier, "provider", None), "model": getattr(verifier, "model", None),
                   "call_timeout_s": call_timeout_s},
        "final_level": summary["level"],
        "analysis_status": summary["status"],
        "first_warning_at_ms": summary["first_warning_at_ms"],
        "first_red_at_ms": summary["first_red_at_ms"],
        "errors": sorted({e["error"] for e in events if e.get("error")}),
        "calls": summary["calls"],
        "reported_cost": round(sum(costs), 6) if costs else None,
        "segments": timeline,
        "summary": summary,
        "events": events,
    }
