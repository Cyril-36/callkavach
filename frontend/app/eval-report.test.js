// node --test frontend/app/eval-report.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PUBLIC_SCHEMA, ReportError, failureKind, fraction, publicReport, readReport } from "./eval-report.js";

const rate = (numerator, denominator) => ({ numerator, denominator, rate: denominator ? numerator / denominator : null });
const QUOTE = "SENTINEL-QUOTE अभी जो OTP आया है वो बताइए";
const TEXT = "SENTINEL-TRANSCRIPT मैं State Bank से बोल रहा हूँ";
// Shaped like backend/evaluation/replay_runner.py output, including the transcript-derived parts that must
// never be published. The numbers are made up for the test only.
const RAW = {
  dataset: "multilingual_development_pilot",
  timing_basis: "synthetic_text_replay_with_real_detector_clock",
  review_status: "independent_language_review_pending",
  score_status: "provisional_pending_independent_fluent_review",
  language_review: { "hi-en": "independent_fluent_review_pending" },
  calls: [
    { call_id: "c1", language: "hi-en", timing_basis: "x", first_warning_at_ms: 9100, first_red_at_ms: 15400, received_at_ms: [4000, 9000],
      risk_events: [{ type: "risk", level: "red", reason: "request for credentials", tactics: [{ tactic: "credential_request", evidence: [{ segment_id: "r1", quote: QUOTE }] }],
        verifier: { provider: "aicredits", prompt_tokens: 900, cost: 0.2, raw_text: TEXT } }],
      detector_summary: { status: "complete", tactics: ["credential_request"], error: null, level: "red" }, failures: [] },
    { call_id: "c2", language: "te-en", first_warning_at_ms: null, first_red_at_ms: null,
      risk_events: [{ type: "risk", level: "none", error: "rejected: #0 unknown tactic 'SENTINEL-MODEL-OUTPUT'", tactics: [] }],
      detector_summary: { status: "incomplete", tactics: [], error: "SENTINEL-ERROR detail" },
      failures: ["analysis timed out after 8 s", "AICredits HTTP 503: SENTINEL-UPSTREAM body", "#0 unknown tactic 'SENTINEL-MODEL-OUTPUT'"] },
  ],
  metrics: {
    overall: { scam_recall: rate(1, 1), false_alarm_rate: rate(0, 1), warned_before_ask: rate(1, 1), median_time_to_alert_ms: 15400, detected_scams: 1, missed_scams: 0, scams_without_ask: 0 },
    by_language: { "hi-en": { scam_recall: rate(1, 1), false_alarm_rate: rate(0, 0), warned_before_ask: rate(1, 1) }, "te-en": { scam_recall: rate(0, 0), false_alarm_rate: rate(0, 1), warned_before_ask: rate(0, 0) } },
  },
  metric_definitions: { false_alarm_rate: "genuine calls with an emitted RED alert / all genuine calls" },
  amber_warning_rates: { overall: { genuine_amber_warning_rate: rate(0, 1), scam_amber_warning_rate: rate(1, 1) }, by_language: {} },
  latency: { verifier_calls: 6, median_verifier_latency_ms: 4100, post_receive_samples: 5, median_post_receive_delay_ms: 4300 },
  failure_calls: 1,
  reproducibility: { repo_commit: "75b8577abcdef", uncommitted_changes: false, provider: "aicredits", model: "gemini-2.5-flash", prompt_version: "tactics-v1",
    run_completed_at_utc: "2026-10-01T10:00:00+00:00", timeouts_s: { provider_http: 8 },
    api_usage: { detector_requests: 6, prompt_tokens: 5000, reported_cost_total: 1.234, reported_cost_unit: "provider-defined; not inferred by runner", reported_cost_is_partial: true } },
};

test("the public export contains no transcript, evidence, model output or verifier metadata", () => {
  const text = JSON.stringify(publicReport(RAW));
  // Aggregate numbers such as verifier_calls are fine; the raw objects and any text from the run are not.
  for (const banned of ["SENTINEL", "risk_events", "evidence", "quote", '"verifier":', '"tactics":', "raw_text", "received_at_ms", "prompt_tokens", "\"language_review\":", "detector_summary"]) {
    assert.ok(!text.includes(banned), `public export contains ${banned}`);
  }
  assert.equal(publicReport(RAW).schema, PUBLIC_SCHEMA);
});

test("the export keeps the numbers the tab shows, and failures only as fixed categories", () => {
  const pub = publicReport(RAW);
  assert.deepEqual(pub.metrics.overall.scam_recall, { numerator: 1, denominator: 1 });
  assert.deepEqual(pub.calls[1].failures, ["analysis timed out", "provider HTTP 503", "model reply failed validation"]);
  assert.equal(pub.calls[0].status, "complete");
  assert.equal(pub.reproducibility.api_usage.reported_cost_total, 1.234);
});

test("the export command writes the public form and nothing else", () => {
  const dir = mkdtempSync(join(tmpdir(), "ck-eval-"));
  writeFileSync(join(dir, "raw.json"), JSON.stringify(RAW));
  execFileSync(process.execPath, [new URL("./export-eval-report.mjs", import.meta.url).pathname, join(dir, "raw.json"), join(dir, "out.json")]);
  const written = readFileSync(join(dir, "out.json"), "utf8");
  assert.ok(!written.includes("SENTINEL") && !written.includes("risk_events"));
  assert.equal(JSON.parse(written).schema, PUBLIC_SCHEMA);
});

test("the app refuses to show a raw runner report", () => {
  assert.throws(() => readReport(RAW), /raw run_pilot\.py report.*export-eval-report/);
});

test("reads the public report without recomputing its numbers", () => {
  const r = readReport(publicReport(RAW));
  assert.deepEqual(r.tiles.map((t) => t.frac), ["1 / 1", "0 / 1", "1 / 1", "0 / 1"]);
  assert.equal(r.provider, "aicredits · gemini-2.5-flash · prompt tactics-v1");
  assert.equal(r.commit, "75b8577");
  assert.match(r.cost, /1\.23 .*partial/);
  assert.deepEqual(r.languages.map((l) => l.lang), ["Hindi–English", "Telugu–English"]);
  assert.equal(r.calls[1].failures, "analysis timed out; provider HTTP 503; model reply failed validation");
  assert.equal(r.calls[1].firstRed, "unknown (failed)");
  assert.equal(r.calls[0].firstRed, "15.4 s");
});

test("caveats state the timing basis, small size and failures", () => {
  const text = readReport(publicReport(RAW)).caveats.join(" ");
  assert.match(text, /not audio-to-warning latency/);
  assert.match(text, /2 development call\(s\)/);
  assert.match(text, /1 call\(s\) had detector failures/);
  assert.match(text, /provisional/);
});

test("a report without a reproducibility manifest is flagged as unverified", () => {
  const { reproducibility, ...rest } = RAW;
  assert.match(readReport(publicReport(rest)).caveats[0], /unverified/);
});

test("anything that is not a report is refused rather than guessed at", () => {
  for (const bad of [null, [], {}, { samples: { total: 64 }, overall: {} }, { schema: PUBLIC_SCHEMA, metrics: { overall: {} }, calls: [] }]) {
    assert.throws(() => readReport(bad), ReportError);
  }
  assert.throws(() => publicReport({ calls: [] }), ReportError);
});

test("failure categories never carry free text", () => {
  assert.equal(failureKind("Gemini HTTP 429: You exceeded your current quota"), "provider HTTP 429");
  assert.equal(failureKind("something odd: SENTINEL"), "other failure");
});

test("empty denominators never show as a percentage", () => {
  assert.deepEqual(fraction(rate(0, 0)), { frac: "0 / 0", pct: "no samples" });
  assert.deepEqual(fraction(undefined), { frac: "—", pct: "not reported" });
});
