"""Text replay of one call through SessionDetector, for the offline evaluation runner.

Input is exactly the output of backend/evaluation/detector_view.py (all finalized segments of a call):
  {"language": str, "segments": [{"text": str, "start_at_ms": int, "end_at_ms": int}, ...]}
Any other key is rejected, so labels, family IDs, speaker labels and first-ask times cannot reach the
detector. Segments get opaque IDs r1, r2, ... in order.

Timing model ("scripted_end_plus_measured_processing"): segment i is fed at its scripted end_at_ms, and the
detector clock then advances by real elapsed processing time, so an emitted_at_ms is the scripted time the
segment finished plus the measured analysis latency. Replay is sequential: each segment is analysed before
the next is fed, so it does not model analysis backlog when speech outpaces analysis, and there is no Stop
deadline (live Stop behaviour is measured by e2e_harness.py instead). The per-call timeout, validation and
risk policy are the production ones.

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

    def clock() -> int:
        return int(clock_state["base_ms"] + (loop.time() - clock_state["fed_at"]) * 1000)

    async def emit(event):
        events.append(event)

    detector = SessionDetector(verifier, emit, clock=clock, call_timeout_s=call_timeout_s, min_interval_s=0.0)
    try:
        for i, s in enumerate(view["segments"]):
            clock_state["base_ms"], clock_state["fed_at"] = s["end_at_ms"], loop.time()
            detector.add(Segment(f"r{i + 1}", s["text"], s["end_at_ms"]))
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
        "clock": "scripted_end_plus_measured_processing",
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
        "summary": summary,
        "events": events,
    }
