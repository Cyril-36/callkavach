#!/usr/bin/env node
// Publishes a development replay result for the Evaluation tab without its transcript-derived content.
//
//   uv run --no-project --with httpx python -m backend.evaluation.run_pilot --output /tmp/callkavach-dev-replay.json
//   node frontend/app/export-eval-report.mjs /tmp/callkavach-dev-replay.json /tmp/callkavach-public-eval.json
//
// Reads the raw run_pilot.py report and writes only the whitelisted public form. Both files are live results
// and stay outside the repository: an output path inside it is refused. The relay serves the public file
// from CALLKAVACH_EVAL_REPORT (a path) or CALLKAVACH_EVAL_REPORT_JSON (its contents); see DEPLOY.md.
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { publicReport, readReport } from "./eval-report.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

// Resolves symlinks in the existing part of the path, so an alias into the repository is caught too.
function insideRepo(path) {
  let dir = resolve(path), rest = "";
  for (;;) {
    try { const real = realpathSync(dir); return (real + rest + sep).startsWith(realpathSync(REPO) + sep); }
    catch { const up = dirname(dir); if (up === dir) return false; rest = sep + dir.slice(up.length + 1) + rest; dir = up; }
  }
}

const [input, output] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: node frontend/app/export-eval-report.mjs RAW_RUN_PILOT_REPORT.json PUBLIC_OUTPUT.json  (both outside the repository)");
  process.exit(2);
}
if (insideRepo(output)) {
  console.error(`error: refusing to write ${output} inside the repository; live results stay out of Git. Use a path such as /tmp/callkavach-public-eval.json.`);
  process.exit(2);
}
const pub = publicReport(JSON.parse(readFileSync(input, "utf8")));
readReport(pub); // the app must be able to show it
writeFileSync(output, `${JSON.stringify(pub, null, 1)}\n`);
const o = pub.metrics.overall;
console.log(`Wrote ${output}: ${pub.calls.length} calls, red recall ${o.scam_recall?.numerator}/${o.scam_recall?.denominator}, `
  + `red false alarms ${o.false_alarm_rate?.numerator}/${o.false_alarm_rate?.denominator}. No transcript text, quotes or verifier metadata.`);
