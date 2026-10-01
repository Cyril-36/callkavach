// The Evaluation tab's data path. Pure: no DOM, so it runs under `node --test`.
//
// backend/evaluation/run_pilot.py writes a raw report that contains transcript-derived text: risk events
// with evidence quotes, detector summaries and raw verifier metadata. That report must stay outside the
// repository. publicReport() builds the only thing the app may publish, `callkavach.public_eval.v1`, by
// copying an explicit whitelist of numbers, fixed labels and status values. Free text from the run
// (failure messages, which can echo model output) is reduced to fixed categories. readReport() accepts
// only that public form and refuses a raw report, so the raw one can't be published by mistake.
// Every number shown comes from the report; nothing is recomputed or rounded into a stronger claim.

export const PUBLIC_SCHEMA = "callkavach.public_eval.v1";
const LANG_NAMES = { "hi-en": "Hindi–English", "te-en": "Telugu–English", en: "English", hi: "Hindi", te: "Telugu" };

export class ReportError extends Error {}

// --- whitelist helpers: anything not matching the expected type becomes null ---
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const int = (v) => (Number.isInteger(v) ? v : null);
const bool = (v) => (typeof v === "boolean" ? v : null);
const label = (v, max = 80) => (typeof v === "string" && /^[\w .:+()/,-]*$/.test(v) ? v.slice(0, max) : null);
const rate = (r) => (r && typeof r === "object" && int(r.numerator) !== null && int(r.denominator) !== null
  ? { numerator: r.numerator, denominator: r.denominator } : null);
const pick = (obj, fields) => Object.fromEntries(fields.map(([k, f]) => [k, f(obj ? obj[k] : undefined)]));
const mapObject = (obj, f) => Object.fromEntries(Object.entries(obj && typeof obj === "object" ? obj : {})
  .filter(([k]) => label(k, 20) !== null).map(([k, v]) => [k, f(v)]));

const METRICS = [["scam_recall", rate], ["false_alarm_rate", rate], ["warned_before_ask", rate],
  ["median_time_to_alert_ms", num], ["detected_scams", int], ["missed_scams", int], ["scams_without_ask", int]];
const AMBER = [["genuine_amber_warning_rate", rate], ["scam_amber_warning_rate", rate]];
const STATUSES = new Set(["complete", "incomplete", "pending", "unavailable"]);

// Failure messages can contain model output (e.g. an unknown tactic name), so only a fixed category is kept.
export function failureKind(text) {
  const t = String(text);
  if (/timed out/i.test(t)) return "analysis timed out";
  const http = t.match(/HTTP (\d{3})/);
  if (http) return `provider HTTP ${http[1]}`;
  if (/request failed/i.test(t)) return "provider request failed";
  if (/budget/i.test(t)) return "call budget exhausted";
  if (/rejected|not found|unknown tactic|unknown status|not in this request|over-long|non-string|has fields|not an object|not a list/i.test(t)) {
    return "model reply failed validation";
  }
  return "other failure";
}

// "First warning (amber or red) before the scripted first dangerous ask", derived reproducibly from the
// frozen run's first_warning_at_ms and the development set's ground truth (the runner scores red only).
// Every scam call with a labelled ask is in the denominator, including calls with detector failures.
export function warningBeforeAsk(raw, groundTruth) {
  const truth = new Map((Array.isArray(groundTruth) ? groundTruth : []).map((g) => [g.call_id, g]));
  const ids = raw.calls.map((c) => c.call_id);
  if (ids.length !== truth.size || ids.some((id) => !truth.has(id))) throw new ReportError("ground truth and run have different call IDs");
  let numerator = 0, denominator = 0, withFailures = 0;
  const leads = [];
  for (const c of raw.calls) {
    const g = truth.get(c.call_id);
    if (g.label !== "scam" || typeof g.first_ask_at_ms !== "number") continue;
    denominator++;
    if ((c.failures || []).length) withFailures++;
    if (typeof c.first_warning_at_ms === "number" && c.first_warning_at_ms < g.first_ask_at_ms) {
      numerator++; leads.push(g.first_ask_at_ms - c.first_warning_at_ms);
    }
  }
  return { numerator, denominator, lead_min_ms: leads.length ? Math.min(...leads) : null, lead_max_ms: leads.length ? Math.max(...leads) : null,
    scam_calls_with_failures: withFailures, basis: "synthetic_text_replay_frozen_run_plus_development_ground_truth" };
}

export function publicReport(raw, { groundTruth = null, reviewUpdate = null } = {}) {
  if (!raw || typeof raw !== "object" || !raw.metrics || !Array.isArray(raw.calls)) {
    throw new ReportError("not a run_pilot.py report (expected metrics and calls)");
  }
  const rep = raw.reproducibility;
  const usage = rep && rep.api_usage;
  return {
    // Added at export, not by the run: the run's own fields below are copied unchanged.
    first_warning_before_ask: groundTruth ? warningBeforeAsk(raw, groundTruth) : null,
    review_update: reviewUpdate === null ? null : label(reviewUpdate, 160),
    schema: PUBLIC_SCHEMA,
    dataset: label(raw.dataset),
    timing_basis: label(raw.timing_basis),
    score_status: label(raw.score_status),
    review_status: label(raw.review_status),
    metrics: { overall: pick(raw.metrics.overall, METRICS), by_language: mapObject(raw.metrics.by_language, (m) => pick(m, METRICS)) },
    amber_warning_rates: raw.amber_warning_rates ? {
      overall: pick(raw.amber_warning_rates.overall, AMBER),
      by_language: mapObject(raw.amber_warning_rates.by_language, (m) => pick(m, AMBER)),
    } : null,
    latency: raw.latency ? pick(raw.latency, [["verifier_calls", int], ["median_verifier_latency_ms", num],
      ["post_receive_samples", int], ["median_post_receive_delay_ms", num]]) : null,
    failure_calls: int(raw.failure_calls),
    reproducibility: rep ? {
      ...pick(rep, [["repo_commit", label], ["uncommitted_changes", bool], ["detector_commit", label],
        ["provider", label], ["model", label], ["prompt_version", label], ["run_started_at_utc", label],
        ["run_completed_at_utc", label]]),
      api_usage: usage ? pick(usage, [["detector_requests", int], ["reported_cost_total", num],
        ["reported_cost_is_partial", bool], ["reported_cost_unit", (v) => (typeof v === "string" ? v.slice(0, 60) : null)]]) : null,
    } : null,
    calls: raw.calls.map((c) => ({
      call_id: label(c.call_id, 40),
      language: label(c.language, 20),
      first_warning_at_ms: num(c.first_warning_at_ms),
      first_red_at_ms: num(c.first_red_at_ms),
      status: STATUSES.has(c.detector_summary && c.detector_summary.status) ? c.detector_summary.status : "unknown",
      failures: [...new Set((c.failures || []).map(failureKind))],
    })),
  };
}

export function fraction(r) {
  if (!r || int(r.numerator) === null || int(r.denominator) === null) return { frac: "—", pct: "not reported" };
  return { frac: `${r.numerator} / ${r.denominator}`, pct: r.denominator ? `${Math.round((1000 * r.numerator) / r.denominator) / 10}%` : "no samples" };
}

const seconds = (ms) => (typeof ms === "number" ? `${(ms / 1000).toFixed(1)} s` : "—");

const DEFINITIONS = {
  scam_recall: "scam calls with an emitted RED alert / all scam calls",
  false_alarm_rate: "genuine calls with an emitted RED alert / all genuine calls",
  amber_warning_rates: "calls with an emitted AMBER event / all calls of that label; may also later turn RED",
  failed_sessions: "included in all applicable rate denominators",
};

export function readReport(j) {
  if (!j || typeof j !== "object") throw new ReportError("the file is not a JSON object");
  if (j.schema !== PUBLIC_SCHEMA) {
    const raw = Array.isArray(j.calls) && j.calls.some((c) => c && ("risk_events" in c || "detector_summary" in c));
    throw new ReportError(raw
      ? "this is a raw run_pilot.py report, which contains transcript text and evidence quotes; publish it with frontend/app/export-eval-report.mjs instead"
      : `not a CallKavach public evaluation report (expected schema ${PUBLIC_SCHEMA})`);
  }
  const overall = j.metrics && j.metrics.overall;
  if (!overall || !rate(overall.scam_recall) || !rate(overall.false_alarm_rate) || !Array.isArray(j.calls)) {
    throw new ReportError("the report has no metrics.overall or calls");
  }
  const rep = j.reproducibility || null;
  const amber = (j.amber_warning_rates && j.amber_warning_rates.overall) || {};
  const amberByLang = (j.amber_warning_rates && j.amber_warning_rates.by_language) || {};
  const usage = rep && rep.api_usage;
  const caveats = [];
  if (!rep) caveats.push("No reproducibility manifest: this is not a live run’s output, so treat every number as unverified.");
  if (j.timing_basis) caveats.push(`Timing basis: ${j.timing_basis.replace(/_/g, " ")}. Scripted text replay, not audio-to-warning latency.`);
  if (j.score_status) caveats.push(`Score status at the time of the run: ${j.score_status.replace(/_/g, " ")}.`);
  if (j.review_update) caveats.push(`Since the run: ${j.review_update}.`);
  caveats.push(`${j.calls.length} development call(s). A small synthetic set: percentages are indicative, not an accuracy claim.`);
  const failed = Math.max(j.failure_calls || 0, j.calls.filter((c) => (c.failures || []).length).length);
  if (failed) caveats.push(`${failed} call(s) had detector failures; they stay in every denominator, and a dash in their row means "not known", not "no warning".`);
  const failedCall = (c) => (c.failures || []).length > 0;
  return {
    dataset: j.dataset || "unknown dataset",
    provider: rep && rep.provider ? `${rep.provider} · ${rep.model}${rep.prompt_version ? ` · prompt ${rep.prompt_version}` : ""}` : "provider not recorded",
    commit: rep && rep.repo_commit ? `${String(rep.repo_commit).slice(0, 7)}${rep.uncommitted_changes ? " (with uncommitted changes)" : ""}` : "",
    when: rep ? rep.run_completed_at_utc : null,
    cost: usage && typeof usage.reported_cost_total === "number" ? `${usage.reported_cost_total.toFixed(2)} provider-reported units (${usage.reported_cost_unit || "unit not stated"}${usage.reported_cost_is_partial ? "; partial: some calls reported no cost" : ""})` : null,
    caveats,
    tiles: [
      { label: "Scams that reached a RED alert", ...fraction(overall.scam_recall), sub: `${overall.missed_scams ?? "?"} missed` },
      { label: "Genuine calls with a RED false alarm", ...fraction(overall.false_alarm_rate), sub: "the warning a listener must never get wrongly", flag: overall.false_alarm_rate.numerator ? "Needs attention" : "" },
      ...(j.first_warning_before_ask ? [{ label: "First warning (amber or red) before the scripted first dangerous ask", ...fraction(j.first_warning_before_ask),
        sub: `synthetic text replay, not phone audio · lead ${seconds(j.first_warning_before_ask.lead_min_ms)}–${seconds(j.first_warning_before_ask.lead_max_ms)}`
          + ` · ${j.first_warning_before_ask.scam_calls_with_failures} of these calls had detector failures` }] : []),
      { label: "RED before the scripted first ask", ...fraction(overall.warned_before_ask), sub: `median time to red ${seconds(overall.median_time_to_alert_ms)} (replay clock); red usually fires on the dangerous request itself` },
      { label: "Genuine calls with an AMBER warning", ...fraction(amber.genuine_amber_warning_rate), sub: "caution, not an accusation" },
    ],
    languages: Object.entries((j.metrics && j.metrics.by_language) || {}).map(([code, m]) => ({
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
      firstWarning: failedCall(c) && c.first_warning_at_ms == null ? "unknown (failed)" : seconds(c.first_warning_at_ms),
      firstRed: failedCall(c) && c.first_red_at_ms == null ? "unknown (failed)" : seconds(c.first_red_at_ms),
      status: c.status || "unknown",
      failures: (c.failures || []).join("; "),
    })),
    definitions: DEFINITIONS,
  };
}
