// Reads the development replay report written by backend/evaluation/run_pilot.py (Navadeep's runner)
// and turns it into display rows. Pure: no DOM, so it runs under `node --test`.
// Every number shown comes from the report; nothing is recomputed or rounded into a stronger claim.

const LANG_NAMES = { "hi-en": "Hindi–English", "te-en": "Telugu–English", en: "English", hi: "Hindi", te: "Telugu" };

export class ReportError extends Error {}

const isRate = (r) => r && typeof r === "object" && Number.isInteger(r.numerator) && Number.isInteger(r.denominator);

export function fraction(r) {
  if (!isRate(r)) return { frac: "—", pct: "not reported" };
  return { frac: `${r.numerator} / ${r.denominator}`, pct: r.denominator ? `${Math.round((1000 * r.numerator) / r.denominator) / 10}%` : "no samples" };
}

const seconds = (ms) => (typeof ms === "number" ? `${(ms / 1000).toFixed(1)} s` : "—");

export function readReport(j) {
  if (!j || typeof j !== "object") throw new ReportError("the file is not a JSON object");
  const overall = j.metrics && j.metrics.overall;
  if (!overall || !isRate(overall.scam_recall) || !isRate(overall.false_alarm_rate) || !Array.isArray(j.calls)) {
    throw new ReportError("not a CallKavach replay report (expected metrics.overall and calls from backend/evaluation/run_pilot.py)");
  }
  const rep = j.reproducibility || null;
  const amber = (j.amber_warning_rates && j.amber_warning_rates.overall) || {};
  const byLang = (j.metrics && j.metrics.by_language) || {};
  const amberByLang = (j.amber_warning_rates && j.amber_warning_rates.by_language) || {};
  const usage = rep && rep.api_usage;
  const caveats = [];
  if (!rep) caveats.push("No reproducibility manifest: this is not a live run’s output, so treat every number as unverified.");
  if (j.timing_basis) caveats.push(`Timing basis: ${j.timing_basis.replace(/_/g, " ")}. Scripted text replay, not audio-to-warning latency.`);
  if (j.score_status) caveats.push(`Score status: ${j.score_status.replace(/_/g, " ")}.`);
  caveats.push(`${j.calls.length} development call(s). A small synthetic set: percentages are indicative, not an accuracy claim.`);
  const failed = Math.max(j.failure_calls || 0, j.calls.filter((c) => (c.failures || []).length).length);
  if (failed) caveats.push(`${failed} call(s) had detector failures; they stay in every denominator, and a dash in their row means "not known", not "no warning".`);
  return {
    dataset: j.dataset || "unknown dataset",
    provider: rep ? `${rep.provider} · ${rep.model}` : "provider not recorded",
    commit: rep ? `${String(rep.repo_commit || "").slice(0, 7)}${rep.uncommitted_changes ? " (with uncommitted changes)" : ""}` : "",
    when: rep ? rep.run_completed_at_utc : null,
    cost: usage && typeof usage.reported_cost_total === "number" ? `${usage.reported_cost_total.toFixed(2)} (${usage.reported_cost_unit || "unit not stated"}${usage.reported_cost_is_partial ? ", partial" : ""})` : null,
    caveats,
    tiles: [
      { label: "Scams that reached a RED alert", ...fraction(overall.scam_recall), sub: `${overall.missed_scams ?? "?"} missed` },
      { label: "Genuine calls with a RED false alarm", ...fraction(overall.false_alarm_rate), sub: "the warning a listener must never get wrongly", flag: overall.false_alarm_rate.numerator ? "Needs attention" : "" },
      { label: "RED before the scripted first ask", ...fraction(overall.warned_before_ask), sub: `median time to red ${seconds(overall.median_time_to_alert_ms)} (replay clock)` },
      { label: "Genuine calls with an AMBER warning", ...fraction(amber.genuine_amber_warning_rate), sub: "caution, not an accusation" },
    ],
    languages: Object.entries(byLang).map(([code, m]) => ({
      lang: LANG_NAMES[code] || code,
      recall: fraction(m.scam_recall).frac,
      falseRed: fraction(m.false_alarm_rate).frac,
      beforeAsk: fraction(m.warned_before_ask).frac,
      genuineAmber: fraction((amberByLang[code] || {}).genuine_amber_warning_rate).frac,
    })),
    latency: j.latency ? { calls: j.latency.verifier_calls, verifier: seconds(j.latency.median_verifier_latency_ms), delay: seconds(j.latency.median_post_receive_delay_ms) } : null,
    calls: j.calls.map((c) => ({
      id: c.call_id,
      lang: LANG_NAMES[c.language] || c.language,
      firstWarning: (c.failures || []).length && c.first_warning_at_ms == null ? "unknown (failed)" : seconds(c.first_warning_at_ms),
      firstRed: (c.failures || []).length && c.first_red_at_ms == null ? "unknown (failed)" : seconds(c.first_red_at_ms),
      status: c.detector_summary ? c.detector_summary.status : "unknown",
      failures: (c.failures || []).join("; "),
    })),
    definitions: j.metric_definitions || {},
  };
}
