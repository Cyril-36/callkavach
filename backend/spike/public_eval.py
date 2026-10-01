"""Server side of the Evaluation tab: serve only a sanitised public report, from outside the repository.

The public form (`callkavach.public_eval.v1`) is made by frontend/app/export-eval-report.mjs from a raw
backend/evaluation/run_pilot.py result. The relay never serves a file from the repository for it. It reads
the report named by one of:
  CALLKAVACH_EVAL_REPORT       path to the exported JSON file (outside the repository)
  CALLKAVACH_EVAL_REPORT_JSON  the exported JSON itself (convenient as a host secret or setting)
and serves it only if every key is on the public whitelist and every string is a plain label, so a raw
report with risk events, evidence quotes or verifier metadata is refused even if configured by mistake.
"""
import json
import os
import re
from pathlib import Path

PUBLIC_SCHEMA = "callkavach.public_eval.v1"
_LABEL = re.compile(r"^[\w .:+()/,-]{0,80}$")
_RATE = {"numerator", "denominator"}
_METRICS = {"scam_recall", "false_alarm_rate", "warned_before_ask", "median_time_to_alert_ms", "detected_scams",
            "missed_scams", "scams_without_ask"}
_AMBER = {"genuine_amber_warning_rate", "scam_amber_warning_rate"}
_TOP = {"schema", "dataset", "timing_basis", "score_status", "review_status", "metrics", "amber_warning_rates",
        "latency", "failure_calls", "reproducibility", "calls", "first_warning_before_ask", "review_update"}
_BEFORE_ASK = {"numerator", "denominator", "lead_min_ms", "lead_max_ms", "scam_calls_with_failures", "basis"}
_REPRO = {"repo_commit", "uncommitted_changes", "detector_commit", "provider", "model", "prompt_version",
          "run_started_at_utc", "run_completed_at_utc", "api_usage"}
_USAGE = {"detector_requests", "reported_cost_total", "reported_cost_is_partial", "reported_cost_unit"}
_LATENCY = {"verifier_calls", "median_verifier_latency_ms", "post_receive_samples", "median_post_receive_delay_ms"}
_CALL = {"call_id", "language", "first_warning_at_ms", "first_red_at_ms", "status", "failures"}
_FAILURE = re.compile(r"^(analysis timed out|provider HTTP \d{3}|provider request failed|call budget exhausted|"
                      r"model reply failed validation|other failure)$")


class NotPublic(ValueError):
    pass


def _keys(obj, allowed, where):
    if not isinstance(obj, dict):
        raise NotPublic(f"{where} is not an object")
    extra = set(obj) - allowed
    if extra:
        raise NotPublic(f"{where} has non-public fields {sorted(extra)[:5]}")


def _scalar(v, where, *, text_limit=None):
    if v is None or isinstance(v, bool) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
        return
    if isinstance(v, str) and (_LABEL.match(v) or (text_limit and len(v) <= text_limit and "\n" not in v)):
        return
    raise NotPublic(f"{where} is not a number, flag or plain label")


def _metrics(m, allowed, where):
    _keys(m, allowed, where)
    for k, v in m.items():
        if isinstance(v, dict):
            _keys(v, _RATE, f"{where}.{k}")
            for kk, vv in v.items():
                _scalar(vv, f"{where}.{k}.{kk}")
        else:
            _scalar(v, f"{where}.{k}")


def validate(report) -> dict:
    """Return the report if it is exactly the public form; raise NotPublic otherwise."""
    _keys(report, _TOP, "report")
    if report.get("schema") != PUBLIC_SCHEMA:
        raise NotPublic(f"schema is not {PUBLIC_SCHEMA}")
    for k in ("dataset", "timing_basis", "score_status", "review_status", "failure_calls"):
        _scalar(report.get(k), k)
    update = report.get("review_update")
    if update is not None and not (isinstance(update, str) and re.match(r"^[\w .:+()/,-]{0,160}$", update)):
        raise NotPublic("review_update is not a plain label")
    before = report.get("first_warning_before_ask")
    if before is not None:
        _keys(before, _BEFORE_ASK, "first_warning_before_ask")
        for k, v in before.items():
            _scalar(v, f"first_warning_before_ask.{k}")
    metrics = report.get("metrics")
    _keys(metrics, {"overall", "by_language"}, "metrics")
    _metrics(metrics.get("overall"), _METRICS, "metrics.overall")
    for lang, m in (metrics.get("by_language") or {}).items():
        _scalar(lang, "metrics.by_language key")
        _metrics(m, _METRICS, f"metrics.by_language.{lang}")
    amber = report.get("amber_warning_rates")
    if amber is not None:
        _keys(amber, {"overall", "by_language"}, "amber_warning_rates")
        _metrics(amber.get("overall") or {}, _AMBER, "amber_warning_rates.overall")
        for lang, m in (amber.get("by_language") or {}).items():
            _scalar(lang, "amber_warning_rates.by_language key")
            _metrics(m, _AMBER, f"amber_warning_rates.by_language.{lang}")
    if report.get("latency") is not None:
        _metrics(report["latency"], _LATENCY, "latency")
    repro = report.get("reproducibility")
    if repro is not None:
        _keys(repro, _REPRO, "reproducibility")
        for k, v in repro.items():
            if k == "api_usage" and v is not None:
                _keys(v, _USAGE, "reproducibility.api_usage")
                for kk, vv in v.items():
                    _scalar(vv, f"api_usage.{kk}", text_limit=60 if kk == "reported_cost_unit" else None)
            elif k != "api_usage":
                _scalar(v, f"reproducibility.{k}")
    calls = report.get("calls")
    if not isinstance(calls, list):
        raise NotPublic("calls is not a list")
    for i, c in enumerate(calls):
        _keys(c, _CALL, f"calls[{i}]")
        for k in ("call_id", "language", "first_warning_at_ms", "first_red_at_ms", "status"):
            _scalar(c.get(k), f"calls[{i}].{k}")
        failures = c.get("failures") or []
        if not isinstance(failures, list) or not all(isinstance(f, str) and _FAILURE.match(f) for f in failures):
            raise NotPublic(f"calls[{i}].failures holds free text, not failure categories")
    return report


def load(env=os.environ):
    """The configured public report, None when none is configured; raises NotPublic or OSError otherwise."""
    inline, path = env.get("CALLKAVACH_EVAL_REPORT_JSON"), env.get("CALLKAVACH_EVAL_REPORT")
    if inline:
        return validate(json.loads(inline))
    if path:
        return validate(json.loads(Path(path).read_text(encoding="utf-8")))
    return None
