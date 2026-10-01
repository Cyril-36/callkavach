// node --test frontend/app/session-core.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  LANGS, STOP_WAIT_MS, freshSession, headlineFor, readStopped, reduce, startMessage, stopMessage, unconfirmedStop,
} from "./session-core.js";

const listening = () => reduce({ ...freshSession("live"), phase: "connecting" }, { type: "ready" }, 0);
const risk = (over = {}) => ({ type: "risk", level: "none", reason: null, analysis: "ok", error: null, tactics: [], analysed_segments: 1, unanalysed_segments: 0, calls: 1, latency_s: 2.1, verifier: { cost: 0.05 }, ...over });
const stopped = (over = {}, analysis = {}) => ({
  type: "stopped", duration_s: 12, segments: 3, dropped_s: 0, transcription: "complete", reason: null, provider_cleanup: "ok",
  analysis: { level: "none", status: "complete", cut_off_by_stop_deadline: false, in_flight_segments: 0, in_flight_for_s: null, queued_segments: 0, error: null, ...analysis },
  ...over,
});

test("start message matches the relay contract and only supported languages are offered", () => {
  assert.deepEqual(LANGS.map((l) => l.stt), ["hi-IN", "te-IN", "en-IN"]);
  assert.deepEqual(startMessage("te"), { type: "start", encoding: "pcm_s16le", channels: 1, sample_rate: 16000, language_code: "te-IN" });
  assert.equal(startMessage("ta").language_code, "hi-IN", "an unsupported code never reaches the relay");
  assert.deepEqual(startMessage("hi", "kavach-demo"), { type: "start", encoding: "pcm_s16le", channels: 1, sample_rate: 16000, language_code: "hi-IN", access_code: "kavach-demo" });
  assert.equal("access_code" in startMessage("hi", ""), false, "no empty code is sent");
  assert.deepEqual(stopMessage(), { type: "stop" });
});

test("the app sends no text message other than start and stop (the relay ends the session on anything else)", () => {
  const src = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  const sends = [...src.matchAll(/\.send\(JSON\.stringify\(([^)]*\))\)/g)].map((m) => m[1]);
  assert.deepEqual(sends.sort(), ["startMessage(langCode, state.accessCode)", "stopMessage()"]);
  assert.doesNotMatch(src, /type: "(pause|resume|gap)"/);
});

test("Stop waits longer than the relay's 6 s deadline plus provider close", () => {
  assert.ok(STOP_WAIT_MS >= 7000);
});

test("analysis unavailable from the start is a visible failure, never 'no warning yet'", () => {
  const s = reduce(listening(), risk({ analysis: "unavailable", error: "LLM provider is off", calls: 0, analysed_segments: 0 }), 0);
  assert.equal(s.analysis, "unavailable");
  const h = headlineFor(s);
  assert.equal(h.tone, "failure");
  assert.match(h.headline, /analysis is unavailable/);
  assert.match(h.body, /NOT checked/);
  assert.match(h.body, /LLM provider is off/);
});

test("a failed analysis call after a warning keeps the warning and the evidence", () => {
  let s = reduce(listening(), { type: "transcript", final: true, segment_id: "a", text: "OTP batao" }, 4.2);
  const tactics = [{ tactic: "credential_request", evidence: [{ segment_id: "a", quote: "OTP batao" }] }];
  s = reduce(s, risk({ level: "red", reason: "request for credentials or remote access", tactics }), 6);
  s = reduce(s, risk({ level: "red", analysis: "unavailable", error: "timed out after 8 s", tactics }), 15);
  assert.equal(s.level, "red");
  assert.equal(s.analysis, "unavailable");
  assert.equal(s.tactics[0].evidence[0].t, 4.2, "quote time is when its segment arrived");
  assert.equal(headlineFor(s).tone, "red");
});

test("warning events are recorded once per level rise and flagged for playback", () => {
  let s = listening();
  s = reduce(s, risk({ level: "amber", reason: "two or more pressure tactics" }), 10);
  assert.equal(s.newEvent.level, "amber");
  s = reduce(s, risk({ level: "amber" }), 12);
  assert.equal(s.newEvent, null, "a repeated amber is not a new warning");
  s = reduce(s, risk({ level: "red" }), 20);
  assert.deepEqual(s.events.map((e) => [e.level, e.t]), [["amber", 10], ["red", 20]]);
  assert.equal(s.cost.toFixed(2), "0.15");
});

test("an unknown level is shown as unreadable", () => {
  const s = reduce(listening(), risk({ level: "purple" }), 1);
  assert.equal(s.level, "unknown");
  assert.equal(headlineFor(s).tone, "failure");
});

test("transcripts are final, deduplicated by segment and empty ones are dropped", () => {
  let s = listening();
  s = reduce(s, { type: "speech", state: "started" }, 1);
  assert.equal(s.speaking, true);
  s = reduce(s, { type: "transcript", final: true, segment_id: "x", text: " hello " }, 2);
  s = reduce(s, { type: "transcript", final: true, segment_id: "x", text: "hello again" }, 3);
  s = reduce(s, { type: "transcript", final: true, segment_id: "y", text: "  " }, 4);
  assert.deepEqual(s.segs, [{ id: "x", text: "hello", t: 2 }]);
  assert.equal(s.speaking, false);
});

test("a complete stop is the only case called fully checked", () => {
  const s = reduce(listening(), stopped(), 12);
  assert.equal(s.stopInfo.complete, true);
  assert.equal(headlineFor(s).headline, "Stopped · no warning was raised");
});

test("incomplete transcription gives an unmistakable incomplete headline", () => {
  const s = reduce(listening(), stopped({ transcription: "incomplete", reason: "1 utterance never finalized" }), 12);
  assert.equal(s.stopInfo.complete, false);
  assert.match(headlineFor(s).headline, /INCOMPLETE/);
  assert.match(s.stopInfo.problems[0].text, /1 utterance never finalized/);
});

test("a Stop-deadline cut-off names the cancelled call and the queued segments", () => {
  const s = reduce(listening(), stopped({}, { status: "pending", cut_off_by_stop_deadline: true, in_flight_segments: 1, in_flight_for_s: 5.3, queued_segments: 2 }), 12);
  assert.equal(s.stopInfo.complete, false);
  assert.equal(s.stopInfo.cutOff, true);
  const text = s.stopInfo.problems.map((p) => p.text).join(" ");
  assert.match(text, /cancelled after 5\.3 s/);
  assert.match(text, /2 segment\(s\) were never checked/);
  assert.match(headlineFor(s).headline, /INCOMPLETE/);
});

test("incomplete or unavailable analysis and dropped audio are each incomplete", () => {
  for (const [over, analysis, pattern] of [
    [{}, { status: "incomplete", unanalysed_segments: 1, error: "HTTP 503" }, /HTTP 503/],
    [{}, { status: "unavailable", error: "no key" }, /unavailable: no key/],
    [{ dropped_s: 0.8 }, {}, /0\.8 s of audio was dropped/],
    [{ analysis: undefined }, {}, /not confirmed complete/],
  ]) {
    const m = stopped(over, analysis);
    if ("analysis" in over) delete m.analysis;
    const si = readStopped(m);
    assert.equal(si.complete, false);
    assert.match(si.problems.map((p) => p.text).join(" "), pattern);
  }
  const clientGap = readStopped(stopped(), { gaps: [{ source: "client", dur: 0.4 }] });
  assert.equal(clientGap.complete, false);
});

test("no stopped reply means unconfirmed and incomplete", () => {
  const s = { ...listening(), phase: "stopped", stopInfo: unconfirmedStop("no reply within 8 s") };
  assert.match(headlineFor(s).headline, /INCOMPLETE/);
  assert.match(s.stopInfo.problems[0].text, /no reply within 8 s/);
});

test("a warning stays visible after an incomplete stop, with the gap called out", () => {
  let s = reduce(listening(), risk({ level: "amber" }), 5);
  s = reduce(s, stopped({}, { level: "amber", status: "pending", cut_off_by_stop_deadline: true, queued_segments: 1 }), 12);
  const h = headlineFor(s);
  assert.equal(h.tone, "amber");
  assert.match(h.body, /NOT checked/);
});

test("a server error ends the session visibly", () => {
  const s = reduce(listening(), { type: "error", code: "provider_error", message: "Transcription failed: boom" }, 3);
  assert.equal(s.phase, "servererror");
  assert.match(s.error, /boom/);
});

test("Stop keeps streaming silence only while a sentence is open or segments are unchecked", async () => {
  const { needsDrain, STOP_DRAIN_MAX_S } = await import("./session-core.js");
  let s = listening();
  assert.equal(needsDrain(s), false);
  s = reduce(s, { type: "speech", state: "started" }, 1);
  assert.equal(needsDrain(s), true, "sentence still open");
  s = reduce(s, { type: "transcript", final: true, segment_id: "a", text: "hello" }, 2);
  assert.equal(needsDrain(s), true, "transcribed but not checked yet");
  s = reduce(s, risk({ analysed_segments: 1 }), 5);
  assert.equal(needsDrain(s), false);
  s = reduce(s, { type: "transcript", final: true, segment_id: "b", text: "more" }, 6);
  s = reduce(s, risk({ analysis: "unavailable", error: "timed out", analysed_segments: 1, unanalysed_segments: 1 }), 14);
  assert.equal(needsDrain(s), false, "a failed check is reported, not waited on");
  assert.ok(STOP_DRAIN_MAX_S <= 15);
});

test("access refusals and the hourly limit are their own failures, not generic server errors", () => {
  const denied = reduce(listening(), { type: "error", code: "access_denied", message: "Access code missing or wrong." }, 0);
  assert.equal(denied.phase, "accessdenied");
  const quota = reduce(listening(), { type: "error", code: "session_quota", message: "This server's limit of 20 sessions per hour has been reached. Try again later." }, 0);
  assert.equal(quota.phase, "quota");
  assert.match(quota.error, /20 sessions per hour/);
});

test("on-screen warning text is exactly the reviewed copy in docs/warning-copy.md", async () => {
  const { WARNING_COPY } = await import("./session-core.js");
  const doc = readFileSync(new URL("../../docs/warning-copy.md", import.meta.url), "utf8");
  const rows = [...doc.matchAll(/^\| (?:Amber|Red) \| [^|]+ \| (.+?) \| `assets\/warnings\/(\w+-\w+)\.wav` \|$/gm)];
  assert.equal(rows.length, 6);
  for (const [, text, key] of rows) assert.equal(WARNING_COPY[key], text, key);
  for (const lang of LANGS.map((l) => l.code)) for (const level of ["amber", "red"]) assert.ok(WARNING_COPY[`${level}-${lang}`]);
});
