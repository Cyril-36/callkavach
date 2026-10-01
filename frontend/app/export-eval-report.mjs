#!/usr/bin/env node
// Publishes a development replay result for the Evaluation tab without its transcript-derived content.
//
//   uv run --no-project --with httpx python -m backend.evaluation.run_pilot --output /tmp/callkavach-dev-replay.json
//   node frontend/app/export-eval-report.mjs /tmp/callkavach-dev-replay.json
//
// Reads the raw run_pilot.py report (keep it outside the repository: it holds evidence quotes) and writes
// only the whitelisted public form to frontend/app/eval/report.json, or to the path given as a second argument.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { publicReport, readReport } from "./eval-report.js";

const [input, output = resolve(dirname(fileURLToPath(import.meta.url)), "eval", "report.json")] = process.argv.slice(2);
if (!input) {
  console.error("usage: node frontend/app/export-eval-report.mjs RAW_RUN_PILOT_REPORT.json [OUTPUT.json]");
  process.exit(2);
}
const pub = publicReport(JSON.parse(readFileSync(input, "utf8")));
readReport(pub); // the app must be able to show it
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, `${JSON.stringify(pub, null, 1)}\n`);
const o = pub.metrics.overall;
console.log(`Wrote ${output}: ${pub.calls.length} calls, red recall ${o.scam_recall?.numerator}/${o.scam_recall?.denominator}, `
  + `red false alarms ${o.false_alarm_rate?.numerator}/${o.false_alarm_rate?.denominator}. No transcript text, quotes or verifier metadata.`);
