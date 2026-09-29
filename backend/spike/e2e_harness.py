"""Repeatable end-to-end run: synthetic WAV -> /ws/audio relay -> real Sarvam STT -> AICredits detector.

Starts the real relay (audio_ws.app) in-process on a free local port and streams each case through
relay_client.stream_wav, the same client relay_smoke.py uses. Every run makes billed Sarvam and LLM calls.
Synthetic audio only (make_samples.sh); no evaluation data or labels are sent to the detector. The case
"note" is for the human reading the report and never leaves this script.

Modes (never mixed in one report):
  production   the relay exactly as configured (analysis call timeout DETECTOR_CALL_TIMEOUT_S = 8 s,
               provider HTTP timeout 8 s, Stop deadline FINALIZE_DEADLINE_S = 6 s).
  measurement  analysis and HTTP timeouts raised to 30 s to observe the latency distribution. Results are
               latency measurements, NOT production-timeout reliability. The Stop deadline is unchanged.

Stop styles: "pause" streams 1.5 s of trailing silence before Stop; "abrupt" sends Stop right after the
speech, so the last utterance is finalized by the flush during the Stop deadline.

Usage:
  bash backend/spike/make_samples.sh
  uv run --no-project --with "fastapi>=0.115" --with "uvicorn>=0.30" --with "websockets>=13" --with httpx \\
      python backend/spike/e2e_harness.py --mode production --stop both --json report.json
"""
import argparse
import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402

import audio_ws  # noqa: E402
from relay_client import stream_wav  # noqa: E402
from verifier_config import make_verifier  # noqa: E402

REPORT_SCHEMA = "callkavach.e2e_report.v1"
MEASUREMENT_TIMEOUT_S = 30.0
CASES = {  # name: (wav in samples/, language, note for the reader only)
    "te_en_digital_arrest": ("te_en_digital_arrest.wav", "te-IN", "synthetic scam: authority, crime, secrecy"),
    "hi_en_kyc": ("hi_en_kyc.wav", "hi-IN", "synthetic scam: bank claim, account block, OTP request"),
    "hi_en_bank_genuine": ("hi_en_bank_genuine.wav", "hi-IN", "synthetic genuine: declined card, never share OTP"),
    "hi_en_delivery_genuine": ("hi_en_delivery_genuine.wav", "hi-IN", "synthetic genuine: delivery code at the door"),
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RelayServer:
    """The real relay app, run by uvicorn in a background thread for the duration of the harness."""

    def __init__(self):
        self.port = _free_port()
        self.server = uvicorn.Server(uvicorn.Config(audio_ws.app, host="127.0.0.1", port=self.port,
                                                    log_level="warning", ws="websockets"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("relay did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/audio"


def configure(mode: str) -> dict:
    if mode == "measurement":
        audio_ws.DETECTOR_CALL_TIMEOUT_S = MEASUREMENT_TIMEOUT_S
        audio_ws.verifier_factory = lambda: make_verifier(timeout_s=MEASUREMENT_TIMEOUT_S)
    verifier, why = audio_ws.verifier_factory()
    info = {"mode": mode, "analysis_call_timeout_s": audio_ws.DETECTOR_CALL_TIMEOUT_S,
            "stop_deadline_s": audio_ws.FINALIZE_DEADLINE_S, "provider_close_timeout_s": audio_ws.PROVIDER_CLOSE_TIMEOUT_S,
            "provider": getattr(verifier, "provider", None), "model": getattr(verifier, "model", None),
            "http_timeout_s": getattr(getattr(verifier, "client", None), "timeout", None) and
            verifier.client.timeout.read, "unavailable_reason": why}
    if verifier:
        asyncio.run(verifier.close())
    return info


def summarise(run: dict) -> dict:
    """Extract the fields an evaluation or reliability review needs from one run's messages."""
    msgs = run["messages"]
    by_type = lambda kind: [m for m in msgs if m["msg"]["type"] == kind]
    risks = [{"client_t": m["t"], **{k: m["msg"].get(k) for k in (
        "emitted_at_ms", "analysed_through_ms", "level", "reason", "analysis", "error", "rejected_findings",
        "analysed_segments", "unanalysed_segments", "calls", "latency_s", "first_warning_at_ms", "first_red_at_ms",
        "verifier")}, "tactics": {t["tactic"]: [q["quote"] for q in t["evidence"]] for t in m["msg"]["tactics"]}}
        for m in by_type("risk")]
    final = run["final"] or {}
    analysis = final.get("analysis") or {}
    costs = [r["verifier"]["cost"] for r in risks if r["verifier"] and r["verifier"].get("cost") is not None]
    latencies = [r["latency_s"] for r in risks if r["latency_s"] is not None]
    transcripts = [{"client_t": m["t"], "segment_id": m["msg"]["segment_id"], "text": m["msg"]["text"]}
                   for m in by_type("transcript")]
    stop_to_end = None if run["stop_sent_t"] is None else round(run["end_t"] - run["stop_sent_t"], 3)
    return {
        "final_type": final.get("type"),
        "transcripts": transcripts,
        "risk_events": risks,
        "gaps": [m["msg"] for m in by_type("gap")],
        "errors": [m["msg"] for m in by_type("error")],
        "stopped": {k: final.get(k) for k in ("transcription", "reason", "provider_cleanup", "dropped_s", "segments",
                                              "utterances", "finals_before_flush", "finals_after_flush")}
        if final.get("type") == "stopped" else None,
        "analysis": analysis,
        "client_timing": {"speech_s": run["speech_s"], "speech_end_t": run["speech_end_t"],
                          "first_transcript_t": transcripts[0]["client_t"] if transcripts else None,
                          "stop_sent_t": run["stop_sent_t"], "end_t": run["end_t"], "stop_to_end_s": stop_to_end},
        "detection": {"final_level": analysis.get("level"), "first_warning_at_ms": analysis.get("first_warning_at_ms"),
                      "first_red_at_ms": analysis.get("first_red_at_ms"), "analysis_status": analysis.get("status"),
                      "cut_off_by_stop_deadline": analysis.get("cut_off_by_stop_deadline"),
                      "calls": analysis.get("calls"), "call_latencies_s": latencies,
                      "reported_cost": round(sum(costs), 4) if costs else None, "cost_unit": "INR (AICredits usage.cost)"},
    }


async def run_cases(url: str, cases: list, stops: list, repeat: int) -> list:
    runs = []
    for r in range(repeat):
        for name in cases:
            wav, lang, note = CASES[name]
            for stop in stops:
                started = time.strftime("%Y-%m-%dT%H:%M:%S")
                try:
                    raw = await stream_wav(url, str(HERE / "samples" / wav), lang,
                                           tail_silence=1.5 if stop == "pause" else 0.0)
                    result = summarise(raw)
                except Exception as e:  # recorded, never hidden
                    result = {"harness_error": f"{type(e).__name__}: {e}"}
                runs.append({"case": name, "note": note, "language": lang, "stop": stop, "repeat": r + 1,
                             "started": started, **result})
                print(_line(runs[-1]), flush=True)
    return runs


def _line(run: dict) -> str:
    if "harness_error" in run:
        return f"{run['case']:24s} {run['stop']:7s} HARNESS ERROR {run['harness_error']}"
    d, t, s = run["detection"], run["client_timing"], run["stopped"] or {}
    return (f"{run['case']:24s} {run['stop']:7s} level={d['final_level']} analysis={d['analysis_status']} "
            f"cut_off={d['cut_off_by_stop_deadline']} first_red_ms={d['first_red_at_ms']} calls={d['calls']} "
            f"lat={d['call_latencies_s']} cost={d['reported_cost']} transcription={s.get('transcription')} "
            f"stop->end={t['stop_to_end_s']}s errors={len(run['errors'])}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["production", "measurement"], default="production")
    p.add_argument("--stop", choices=["pause", "abrupt", "both"], default="both")
    p.add_argument("--cases", nargs="*", default=list(CASES))
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--json", help="write the full report here")
    args = p.parse_args()
    missing = [n for n in args.cases if not (HERE / "samples" / CASES[n][0]).exists()]
    if missing:
        print(f"missing samples for {missing}; run: bash backend/spike/make_samples.sh", file=sys.stderr)
        return 2
    config = configure(args.mode)
    if config["unavailable_reason"]:
        print(f"BLOCKED: {config['unavailable_reason']}", file=sys.stderr)
        return 2
    print(json.dumps(config))
    stops = ["pause", "abrupt"] if args.stop == "both" else [args.stop]
    with RelayServer() as relay:
        runs = asyncio.run(run_cases(relay.url, args.cases, stops, args.repeat))
    report = {"schema": REPORT_SCHEMA, "config": config, "runs": runs,
              "limitations": ["synthetic single-voice TTS audio, not speakerphone or real speech",
                              "one machine, local relay; no two-device or network measurement",
                              "small number of runs; not an accuracy or reliability estimate"]}
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
