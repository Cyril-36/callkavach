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
    assert r["schema"] == SCHEMA and r["clock"] == "sequential_replay" and r["valid_for_live_timing_metrics"] is False
    assert r["final_level"] == "red" and r["analysis_status"] == "complete" and r["errors"] == []
    assert r["segment_count"] == 3 and r["calls"] == 3 and r["reported_cost"] == pytest.approx(0.3)
    # emitted = scripted segment end + measured processing (about 50 ms here), never before the segment ended
    assert [e["level"] for e in r["events"]] == ["none", "amber", "red"]
    for event, seg in zip(r["events"], VIEW["segments"]):
        assert seg["end_at_ms"] + 40 <= event["emitted_at_ms"] <= seg["end_at_ms"] + 1000
    assert r["first_warning_at_ms"] == r["events"][1]["emitted_at_ms"]
    assert r["first_red_at_ms"] == r["events"][2]["emitted_at_ms"]
    assert r["config"] == {"provider": "mock", "model": "mock-model", "call_timeout_s": 8.0}
    assert [s["effective_receive_ms"] for s in r["segments"]] == [4000, 9000, 14000]  # gaps exceed processing
    assert all(s["delayed_by_ms"] == 0 for s in r["segments"])


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
    assert out["detection"]["cost_unit"] is None  # provider absent: never guess the currency
    assert out["detection"]["call_latencies_s"] == [3.2] and out["detection"]["cut_off_by_stop_deadline"] is False
    assert out["transcripts"] == [{"client_t": 13.4, "segment_id": "a", "text": "OTP"}]
    assert out["risk_events"][0]["tactics"] == {"credential_request": ["OTP"]}
    assert out["client_timing"]["stop_to_end_s"] == 2.5 and out["stopped"]["transcription"] == "complete"


def test_harness_cost_unit_requires_aicredits_provenance():
    import e2e_harness
    risk = {"type": "risk", "verifier": {"provider": "aicredits", "cost": 0.25}, "tactics": [], "latency_s": None}
    run = {"messages": [{"t": 1.0, "msg": risk}], "final": None, "speech_s": 0,
           "speech_end_t": 0, "stop_sent_t": None, "end_t": 1.0}
    assert e2e_harness.summarise(run)["detection"]["cost_unit"] == "INR (AICredits usage.cost)"
    risk["verifier"] = {"provider": "gemini", "cost": None}
    result = e2e_harness.summarise(run)["detection"]
    assert result["reported_cost"] is None and result["cost_unit"] is None


@pytest.mark.asyncio
async def test_slow_earlier_analysis_never_rewinds_the_replay_clock():
    """The first analysis (300 ms) finishes after the second and third segments' scripted ends (100 ms apart)."""
    view = {"language": "hi", "segments": [
        {"text": "मैं बैंक से बोल रहा हूँ", "start_at_ms": 0, "end_at_ms": 1000},
        {"text": "आपका अकाउंट आज ब्लॉक हो जाएगा", "start_at_ms": 1000, "end_at_ms": 1100},
        {"text": "अभी जो OTP आया है वो बताइए", "start_at_ms": 1100, "end_at_ms": 1200},
    ]}
    r = await replay_text_call(view, ScriptedVerifier(SCRIPT, delay=0.3))
    emitted = [e["emitted_at_ms"] for e in r["events"]]
    received = [s["effective_receive_ms"] for s in r["segments"]]
    assert emitted == sorted(emitted) and len(set(emitted)) == 3, f"emission times went backwards: {emitted}"
    assert received == sorted(received)
    assert [s["scripted_end_at_ms"] for s in r["segments"]] == [1000, 1100, 1200], "scripted times preserved"
    for i in (1, 2):  # each later segment is received no earlier than the previous emission
        assert received[i] >= emitted[i - 1] and r["segments"][i]["delayed_by_ms"] > 0
    assert received[0] == 1000 and r["segments"][0]["delayed_by_ms"] == 0
    assert [e["analysed_through_ms"] for e in r["events"]] == received
    for e, rec in zip(r["events"], received):
        assert e["emitted_at_ms"] >= rec + 250, "emission includes the measured processing time"
    assert r["first_red_at_ms"] == emitted[2] and r["first_red_at_ms"] > 1200


# --- e2e report location: never inside the repository by default (mock-only, no network) ---

@pytest.fixture
def harness(monkeypatch):
    import e2e_harness

    def no_setup(mode):
        raise AssertionError("the report path must be checked before any setup or paid call")
    monkeypatch.setattr(e2e_harness, "configure", no_setup)
    return e2e_harness


def test_report_paths_inside_the_repository_are_refused(harness, tmp_path, monkeypatch):
    root = harness.REPO_ROOT
    monkeypatch.chdir(root)
    link = tmp_path / "repo-alias"
    link.symlink_to(root / "backend", target_is_directory=True)
    for inside in ["e2e_report.json",  # the previously documented, relative path
                   str(root / "e2e_report.json"),
                   str(root / "backend" / "spike" / "report.json"),
                   str(tmp_path / ".." / tmp_path.name / "repo-alias" / "r.json"),
                   str(link / "spike" / "r.json"),  # a symlink into the repository
                   "backend/../backend/spike/r.json"]:
        why = harness.report_path_error(inside)
        assert why and "inside the repository" in why and "transcript" in why, inside


def test_report_paths_outside_the_repository_are_allowed(harness, tmp_path):
    for outside in ["/tmp/callkavach-e2e-report.json", str(tmp_path / "report.json")]:
        assert harness.report_path_error(outside) is None, outside


def test_main_refuses_an_in_repo_report_before_any_setup(harness, capsys):
    target = harness.REPO_ROOT / "e2e_report.json"
    assert harness.main(["--json", str(target), "--stop", "pause"]) == 2
    err = capsys.readouterr().err
    assert "refusing to write the report inside the repository" in err and "/tmp/callkavach-e2e-report.json" in err
    assert not target.exists()


def test_allow_flag_lets_an_in_repo_path_past_the_check(harness, tmp_path, monkeypatch):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"")  # only has to exist; setup is stopped before it is read
    monkeypatch.setattr(harness, "CASES", {"x": (str(wav), "te-IN", "test")})
    with pytest.raises(AssertionError, match="checked before any setup"):
        harness.main(["--json", str(harness.REPO_ROOT / "r.json"), "--allow-report-in-repo", "--cases", "x"])


def test_every_sample_in_the_app_and_harness_has_a_committed_wav():
    """Sample mode on a deployed server needs the WAVs; the app list and the harness cases must agree."""
    import re
    import e2e_harness
    app_js = (e2e_harness.REPO_ROOT / "frontend" / "app" / "app.js").read_text(encoding="utf-8")
    app_ids = re.findall(r'\{ id: "(\w+)", title:', app_js)
    assert len(app_ids) == len(set(app_ids)) >= 11
    assert set(app_ids) == set(e2e_harness.CASES), "app samples and harness cases differ"
    for name, (wav, language, _note) in e2e_harness.CASES.items():
        path = e2e_harness.HERE / "samples" / wav
        assert path.is_file() and path.stat().st_size > 100_000, f"missing or empty {wav}"
        assert language == ("te-IN" if name.startswith("te_") else "hi-IN"), name
