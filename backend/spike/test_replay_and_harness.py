"""Tests for the evaluation replay contract and the e2e harness report extraction. No network, no paid calls."""
import asyncio
import json

import pytest

from replay import SCHEMA, replay_text_call

VIEW = {"language": "hi", "segments": [
    {"text": "मैं बैंक से बोल रहा हूँ", "start_at_ms": 0, "end_at_ms": 4000},
    {"text": "आपका अकाउंट आज ब्लॉक हो जाएगा", "start_at_ms": 4500, "end_at_ms": 9000},
    {"text": "अभी जो OTP आया है वो बताइए", "start_at_ms": 9500, "end_at_ms": 14000},
]}


class ScriptedVerifier:
    provider, model = "mock", "mock-model"

    def __init__(self, script, delay=0.0):
        self.script, self.delay, self.requests, self.last_call = script, delay, [], None

    async def analyse(self, request):
        self.requests.append(json.loads(json.dumps(request)))
        await asyncio.sleep(self.delay)
        new = [s["segment_id"] for s in request["segments"] if s["new"]][-1]
        result = self.script.get(new, [])
        if isinstance(result, Exception):
            raise result
        self.last_call = {"cost": 0.1}
        return result


def f(tactic, alias, quote):
    return {"tactic": tactic, "status": "present", "segment_id": alias, "quote": quote}


SCRIPT = {"seg1": [f("claimed_authority", "seg1", "बैंक से बोल रहा हूँ")],
          "seg2": [f("threat_or_fabricated_crime", "seg2", "अकाउंट आज ब्लॉक हो जाएगा")],
          "seg3": [f("credential_request", "seg3", "OTP आया है वो बताइए")]}


@pytest.mark.asyncio
async def test_replay_result_contract_and_emission_times():
    v = ScriptedVerifier(SCRIPT, delay=0.05)
    r = await replay_text_call(VIEW, v)
    assert r["schema"] == SCHEMA and r["clock"] == "scripted_end_plus_measured_processing"
    assert r["final_level"] == "red" and r["analysis_status"] == "complete" and r["errors"] == []
    assert r["segment_count"] == 3 and r["calls"] == 3 and r["reported_cost"] == pytest.approx(0.3)
    # emitted = scripted segment end + measured processing (about 50 ms here), never before the segment ended
    assert [e["level"] for e in r["events"]] == ["none", "amber", "red"]
    for event, seg in zip(r["events"], VIEW["segments"]):
        assert seg["end_at_ms"] + 40 <= event["emitted_at_ms"] <= seg["end_at_ms"] + 1000
    assert r["first_warning_at_ms"] == r["events"][1]["emitted_at_ms"]
    assert r["first_red_at_ms"] == r["events"][2]["emitted_at_ms"]
    assert r["config"] == {"provider": "mock", "model": "mock-model", "call_timeout_s": 8.0}


@pytest.mark.asyncio
async def test_replay_feeds_prefixes_in_order_with_opaque_ids_only():
    v = ScriptedVerifier(SCRIPT)
    await replay_text_call(VIEW, v)
    assert [[s["segment_id"] for s in req["segments"]] for req in v.requests] == [
        ["seg1"], ["seg1", "seg2"], ["seg1", "seg2", "seg3"]], "future segments leaked"
    blob = json.dumps(v.requests)
    assert "start_at_ms" not in blob and "end_at_ms" not in blob and '"hi"' not in blob


@pytest.mark.asyncio
@pytest.mark.parametrize("view", [
    {**VIEW, "label": "scam"},
    {**VIEW, "first_ask_at_ms": 9500},
    {"language": "hi", "segments": [{**VIEW["segments"][0], "speaker": "caller"}]},
    {"language": "hi", "segments": [{**VIEW["segments"][0], "segment_id": "s1"}]},
    {"language": "hi", "segments": [{"text": "x", "start_at_ms": "0", "end_at_ms": 1}]},
    {"language": "hi", "segments": [VIEW["segments"][1], VIEW["segments"][0]]},  # out of order
    {"segments": VIEW["segments"]},
])
async def test_replay_rejects_anything_but_a_detector_view(view):
    v = ScriptedVerifier(SCRIPT)
    with pytest.raises(ValueError):
        await replay_text_call(view, v)
    assert v.requests == [], "nothing may reach the verifier from a rejected input"


@pytest.mark.asyncio
async def test_replay_reports_failures_instead_of_a_clean_negative():
    from detector import VerifierError
    v = ScriptedVerifier({**SCRIPT, "seg3": VerifierError("AICredits HTTP 503: down")})
    r = await replay_text_call(VIEW, v)
    assert r["analysis_status"] == "incomplete" and r["final_level"] == "amber"
    assert r["first_red_at_ms"] is None and any("503" in e for e in r["errors"])


@pytest.mark.asyncio
async def test_replay_uses_the_production_call_timeout():
    v = ScriptedVerifier(SCRIPT, delay=0.3)
    r = await replay_text_call({"language": "hi", "segments": VIEW["segments"][:1]}, v, call_timeout_s=0.1)
    assert r["analysis_status"] == "incomplete" and any("timed out after 0.1 s" in e for e in r["errors"])


# --- e2e harness report extraction (no server, no network) ---

def test_harness_summarise_extracts_detection_fields():
    import e2e_harness
    risk = {"type": "risk", "emitted_at_ms": 16198, "analysed_through_ms": 12900, "level": "red", "reason": "x",
            "analysis": "ok", "error": None, "rejected_findings": 0, "analysed_segments": 1, "unanalysed_segments": 0,
            "calls": 1, "latency_s": 3.2, "first_warning_at_ms": 16198, "first_red_at_ms": 16198,
            "verifier": {"cost": 0.17, "returned_model": "gemini-2.5-flash"},
            "tactics": [{"tactic": "credential_request", "evidence": [{"segment_id": "a", "quote": "OTP"}]}]}
    stopped = {"type": "stopped", "transcription": "complete", "reason": None, "provider_cleanup": "ok", "dropped_s": 0.0,
               "segments": 1, "utterances": 1, "finals_before_flush": 1, "finals_after_flush": 0,
               "analysis": {"level": "red", "status": "complete", "first_warning_at_ms": 16198, "first_red_at_ms": 16198,
                            "cut_off_by_stop_deadline": False, "calls": 1}}
    run = {"messages": [{"t": 0.3, "msg": {"type": "ready"}},
                        {"t": 13.4, "msg": {"type": "transcript", "segment_id": "a", "text": "OTP"}},
                        {"t": 16.6, "msg": risk}, {"t": 16.7, "msg": stopped}],
           "speech_s": 11.9, "speech_end_t": 12.5, "stop_sent_t": 14.2, "end_t": 16.7, "final": stopped}
    out = e2e_harness.summarise(run)
    assert out["detection"]["first_red_at_ms"] == 16198 and out["detection"]["reported_cost"] == 0.17
    assert out["detection"]["call_latencies_s"] == [3.2] and out["detection"]["cut_off_by_stop_deadline"] is False
    assert out["transcripts"] == [{"client_t": 13.4, "segment_id": "a", "text": "OTP"}]
    assert out["risk_events"][0]["tactics"] == {"credential_request": ["OTP"]}
    assert out["client_timing"]["stop_to_end_s"] == 2.5 and out["stopped"]["transcription"] == "complete"
