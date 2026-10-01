// node --test frontend/app/eval-report.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { ReportError, fraction, readReport } from "./eval-report.js";

const rate = (numerator, denominator) => ({ numerator, denominator, rate: denominator ? numerator / denominator : null });
// Shaped like backend/evaluation/replay_runner.py output; the numbers are made up for the test only.
const REPORT = {
  dataset: "multilingual_development_pilot",
  timing_basis: "synthetic_text_replay_with_real_detector_clock",
  score_status: "provisional_pending_independent_fluent_review",
  calls: [
    { call_id: "c1", language: "hi-en", first_warning_at_ms: 9100, first_red_at_ms: 15400, detector_summary: { status: "complete" }, failures: [] },
    { call_id: "c2", language: "te-en", first_warning_at_ms: null, first_red_at_ms: null, detector_summary: { status: "incomplete" }, failures: ["timed out after 8 s"] },
  ],
  metrics: {
    overall: { scam_recall: rate(1, 1), false_alarm_rate: rate(0, 1), warned_before_ask: rate(1, 1), median_time_to_alert_ms: 15400, missed_scams: 0 },
    by_language: { "hi-en": { scam_recall: rate(1, 1), false_alarm_rate: rate(0, 0), warned_before_ask: rate(1, 1) }, "te-en": { scam_recall: rate(0, 0), false_alarm_rate: rate(0, 1), warned_before_ask: rate(0, 0) } },
  },
  amber_warning_rates: { overall: { genuine_amber_warning_rate: rate(0, 1), scam_amber_warning_rate: rate(1, 1) }, by_language: {} },
  latency: { verifier_calls: 6, median_verifier_latency_ms: 4100, post_receive_samples: 5, median_post_receive_delay_ms: 4300 },
  failure_calls: 1,
  metric_definitions: { false_alarm_rate: "genuine calls with an emitted RED alert / all genuine calls" },
  reproducibility: { repo_commit: "75b8577abcdef", uncommitted_changes: false, provider: "aicredits", model: "gemini-2.5-flash", run_completed_at_utc: "2026-10-01T10:00:00+00:00", api_usage: { reported_cost_total: 1.234, reported_cost_unit: "provider-defined; not inferred by runner", reported_cost_is_partial: true } },
};

test("reads the runner's report without recomputing its numbers", () => {
  const r = readReport(REPORT);
  assert.deepEqual(r.tiles.map((t) => t.frac), ["1 / 1", "0 / 1", "1 / 1", "0 / 1"]);
  assert.equal(r.provider, "aicredits · gemini-2.5-flash");
  assert.equal(r.commit, "75b8577");
  assert.match(r.cost, /1\.23 .*partial/);
  assert.deepEqual(r.languages.map((l) => l.lang), ["Hindi–English", "Telugu–English"]);
  assert.equal(r.calls[1].failures, "timed out after 8 s");
  assert.equal(r.calls[0].firstRed, "15.4 s");
});

test("caveats state the timing basis, small size and failures", () => {
  const text = readReport(REPORT).caveats.join(" ");
  assert.match(text, /not audio-to-warning latency/);
  assert.match(text, /2 development call\(s\)/);
  assert.match(text, /1 call\(s\) had detector failures/);
  assert.match(text, /provisional/);
});

test("a report without a reproducibility manifest is flagged as unverified", () => {
  const { reproducibility, ...rest } = REPORT;
  assert.match(readReport(rest).caveats[0], /unverified/);
});

test("anything that is not a runner report is refused rather than guessed at", () => {
  for (const bad of [null, [], {}, { samples: { total: 64 }, overall: {} }, { metrics: { overall: {} }, calls: [] }]) {
    assert.throws(() => readReport(bad), ReportError);
  }
});

test("empty denominators never show as a percentage", () => {
  assert.deepEqual(fraction(rate(0, 0)), { frac: "0 / 0", pct: "no samples" });
  assert.deepEqual(fraction(undefined), { frac: "—", pct: "not reported" });
});
