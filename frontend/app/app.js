// CallKavach listener app: live microphone, sample audio through the real pipeline, replay of a saved
// session log, and a static evaluation report. Talks only to this page's own /ws/audio relay.
import { Resampler, toInt16 } from "../spike/resample.js";
import { PcmSender } from "../spike/pcm-sender.js";
import {
  LANGS, STOP_DRAIN_MAX_S, STOP_TAIL_SILENCE_S, STOP_WAIT_MS, SAMPLE_RATE, freshSession, headlineFor, langByCode,
  needsDrain, reduce, startMessage, stopMessage, unconfirmedStop, WARNING_COPY,
} from "./session-core.js";
import { readReport } from "./eval-report.js";

const READY_TIMEOUT_MS = 12000; // includes the relay opening the transcription session
const CLIP_BASE = "/assets/warnings"; // {amber|red|test}-{lang}.mp3 (or .wav)
const REPORT_URL = "eval/report.json";
const LOG_SCHEMA = "callkavach.session_log.v1";
const SAMPLES = [ // synthetic TTS from backend/spike/make_samples.sh, served from /samples/
  { id: "te_en_digital_arrest", title: "Call about a police case", lang: "te", langName: "Telugu–English", kind: "synthetic", label: "scam" },
  { id: "hi_en_kyc", title: "KYC update call", lang: "hi", langName: "Hindi–English", kind: "synthetic", label: "scam" },
  { id: "hi_en_bank_genuine", title: "Bank call about a declined card", lang: "hi", langName: "Hindi–English", kind: "synthetic", label: "genuine" },
  { id: "hi_en_delivery_genuine", title: "Delivery at the door", lang: "hi", langName: "Hindi–English", kind: "synthetic", label: "genuine" },
  { id: "te_en_customs_parcel", title: "Courier parcel call", lang: "te", langName: "Telugu–English", kind: "synthetic", label: "scam" },
  { id: "te_en_power_cut_scam", title: "Electricity bill call", lang: "te", langName: "Telugu–English", kind: "synthetic", label: "scam" },
  { id: "te_en_power_cut_notice", title: "Power cut notice", lang: "te", langName: "Telugu–English", kind: "synthetic", label: "genuine" },
  { id: "te_en_bank_callback", title: "Bank complaint callback", lang: "te", langName: "Telugu–English", kind: "synthetic", label: "genuine" },
  { id: "hi_en_upi_refund", title: "Refund from an online shop", lang: "hi", langName: "Hindi–English", kind: "synthetic", label: "scam" },
  { id: "hi_en_job_fee", title: "Part-time job offer", lang: "hi", langName: "Hindi–English", kind: "synthetic", label: "scam" },
  { id: "hi_en_emi_reminder", title: "Loan EMI reminder", lang: "hi", langName: "Hindi–English", kind: "synthetic", label: "genuine" },
];
const TONES = {
  neutral: { bg: "#FBF9F4", ink: "#17191E", border: "#17191E", rule: "#CFC8B8", quoteBg: "#EFEBE2", btnBg: "#17191E", btnInk: "#FBF9F4", pattern: "" },
  amber: { bg: "#F5C242", ink: "#1C1405", border: "#1C1405", rule: "rgba(28,20,5,.35)", quoteBg: "rgba(255,255,255,.5)", btnBg: "#1C1405", btnInk: "#F5C242", pattern: "" },
  red: { bg: "#B3261E", ink: "#FFFFFF", border: "#6E120D", rule: "rgba(255,255,255,.4)", quoteBg: "rgba(0,0,0,.24)", btnBg: "#FFFFFF", btnInk: "#8E1B15", pattern: "" },
  failure: { bg: "#2A2D33", ink: "#FFFFFF", border: "#000000", rule: "rgba(255,255,255,.3)", quoteBg: "rgba(255,255,255,.1)", btnBg: "#FFFFFF", btnInk: "#17191E", pattern: "repeating-linear-gradient(135deg,rgba(255,255,255,.07) 0 12px,transparent 12px 24px)" },
};
const MODE_COLOR = { live: "#17191E", sample: "#2747A6", replay: "#5B3B9E", eval: "#17191E" };

const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } return v; };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (t) => (t == null || isNaN(t) ? "–:––" : `${Math.floor(Math.max(0, t) / 60)}:${String(Math.floor(Math.max(0, t) % 60)).padStart(2, "0")}`);
const $ = (id) => document.getElementById(id);

const state = {
  mode: ["live", "sample", "replay", "eval"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "live",
  lang: LANGS.some((l) => l.code === store("callkavach.lang")) ? store("callkavach.lang") : "hi",
  autoSpeak: store("callkavach.autoSpeak") !== "0",
  settingsOpen: false, confirmSwitch: null,
  s: null, // current live/sample session
  playback: null, test: null, share: null, clipStatus: {}, meter: 0, silenced: false,
  sampleId: SAMPLES[0].id, sampleAloud: true,
  replay: { log: null, t: 0, playing: false, speed: 1, sound: true, error: null },
  report: null, reportState: "idle", reportErr: "",
};
let rt = null; // runtime handles of the active session (socket, audio graph, timers)
let out = null; // AudioContext for warning clips and the sample played aloud
const clips = {};

// ---------------------------------------------------------------- session plumbing
function setS(s) { state.s = s; render(); }
function patchS(p) { if (state.s) setS({ ...state.s, ...p }); }
function now() { return rt ? rt.audioT : state.s ? state.s.audioT : 0; }

function wsUrl() { return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/audio`; }

function record(m, t) { if (rt) rt.log.push({ t: Math.round(t * 1000) / 1000, m }); }

function apply(m) {
  if (m.type === "ack") return; // ten per second; they change nothing on screen
  const t = now();
  record(m, t);
  let s = reduce(state.s, m, t);
  const ev = s.newEvent;
  if ("newEvent" in s) { s = { ...s }; delete s.newEvent; }
  setS(s);
  if (ev && state.autoSpeak && !state.silenced) playClip(ev.level, "auto");
}

function openSocket(langCode) {
  const r = rt;
  const ws = new WebSocket(wsUrl());
  ws.binaryType = "arraybuffer";
  r.ws = ws;
  r.readyTimer = setTimeout(() => { if (rt === r && state.s.phase === "connecting") fail("unreachable", "the server did not accept audio within 12 s"); }, READY_TIMEOUT_MS);
  ws.onopen = () => { if (rt === r) { ws.send(JSON.stringify(startMessage(langCode))); patchS({ connection: "open-waiting" }); } };
  ws.onmessage = ({ data }) => {
    if (rt !== r || typeof data !== "string") return;
    let m; try { m = JSON.parse(data); } catch { return; }
    if (m.type === "ready") {
      // The sender exists from the moment the session is listening, so Stop works even while the
      // microphone's audio graph is still being set up (it then sends only the silence tail).
      clearTimeout(r.readyTimer); r.audioT = 0; r.sender = new PcmSender(ws); apply(m); r.onReady?.(); return;
    }
    if (m.type === "stopped") { apply(m); finish(); return; }
    if (m.type === "error") { apply(m); teardown(); if (r.kind === "live") patchS({ mic: "released" }); return; }
    apply(m);
  };
  ws.onclose = (e) => {
    if (rt !== r) return;
    const why = e.code === 1006 ? "connection refused or dropped" : `closed, code ${e.code}${e.reason ? ": " + e.reason : ""}`;
    const ph = state.s.phase;
    if (ph === "stopping") { finish(unconfirmedStop(`the connection closed first: ${why}`)); }
    else if (ph === "connecting") fail("unreachable", why);
    else if (ph === "listening") fail("disconnected", why, { disconnectedAt: r.audioT });
  };
}

async function releaseMic(r) {
  if (!r) return true;
  if (r.node) r.node.port.onmessage = null;
  for (const step of [() => r.source?.disconnect(), () => r.node?.disconnect(), () => r.stream?.getTracks().forEach((t) => { t.onended = null; t.stop(); })]) {
    try { step(); } catch {}
  }
  const ok = !r.stream || r.stream.getTracks().every((t) => t.readyState === "ended");
  r.stream = null;
  if (r.ctx && r.ctx.state !== "closed") { try { await r.ctx.close(); } catch {} }
  r.ctx = null;
  return ok;
}

// Keeps a phone's screen on while listening, so the warning is visible when it arrives. Best effort:
// unsupported browsers and a refused request simply leave the screen's normal timeout in place.
let wakeLock = null, wantLock = false, lockPending = false;
async function holdScreen(on) {
  wantLock = on;
  try {
    if (on && !wakeLock && !lockPending && navigator.wakeLock) {
      lockPending = true;
      const w = await navigator.wakeLock.request("screen").finally(() => { lockPending = false; });
      if (!wantLock) { await w.release(); return; } // the session ended while the request was pending
      wakeLock = w;
      w.addEventListener("release", () => { if (wakeLock === w) wakeLock = null; });
    } else if (!on && wakeLock) { const w = wakeLock; wakeLock = null; await w.release(); }
  } catch { /* unsupported or refused: the screen keeps its normal timeout */ }
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && rt && isActive(state.s)) holdScreen(true); });

function teardown() {
  const r = rt; rt = null;
  holdScreen(false);
  stopClip();
  if (!r) return;
  [r.readyTimer, r.stopTimer].forEach(clearTimeout);
  clearInterval(r.streamTimer); clearInterval(r.tailTimer);
  if (r.ws) { r.ws.onopen = r.ws.onmessage = r.ws.onclose = null; try { if (r.ws.readyState < 2) r.ws.close(1000); } catch {} }
  try { r.aloud?.stop(); } catch {}
  releaseMic(r);
  state.lastLog = r.log.length ? { schema: LOG_SCHEMA, recorded_at: r.startedAt, source: r.kind, language: r.lang, sample: r.sample || null, events: r.log } : state.lastLog;
}

function fail(phase, error, extra = {}) {
  const r = rt; const kind = r?.kind; const audioT = r ? r.audioT : 0;
  teardown();
  setS({ ...state.s, phase, error, audioT, connection: phase === "unreachable" ? "unreachable" : phase === "disconnected" ? "lost" : "closed", mic: kind === "live" ? "released" : state.s.mic, ...extra });
}

// Sends 16 kHz Int16 audio; while a warning clip plays, silence is sent instead so the clip is not
// transcribed. The relay only accepts audio frames and stop after start, so nothing else is sent.
function sendPcm(r, pcm16) {
  if (r.muted) pcm16 = new Int16Array(pcm16.length);
  const dropped = r.sender.droppedSamples;
  r.sender.push(pcm16);
  r.audioT += pcm16.length / SAMPLE_RATE;
  const lost = r.sender.droppedSamples - dropped;
  if (lost) state.s = { ...state.s, gaps: [...state.s.gaps, { t: r.audioT, dur: lost / SAMPLE_RATE, source: "client" }] };
  r.backlog = r.ws.bufferedAmount > 32000;
}

async function startLive() {
  teardown();
  holdScreen(true);
  state.playback = state.test = state.share = null; state.silenced = false;
  const r = rt = { kind: "live", audioT: 0, log: [], startedAt: new Date().toISOString(), lang: state.lang };
  setS({ ...freshSession("live"), phase: "permission", mic: "asking" });
  // Created inside the tap: iOS Safari only lets an AudioContext run if it starts in a user gesture.
  try { r.ctx = new AudioContext(); r.ctx.resume(); } catch {}
  ensureOut(); preloadClips(state.lang);
  if (!navigator.mediaDevices?.getUserMedia) { fail("unsupported", null, { mic: "unsupported" }); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } }); }
  catch (e) {
    if (rt !== r) return;
    const n = e && e.name;
    const phase = n === "NotAllowedError" || n === "SecurityError" ? "denied" : n === "NotFoundError" || n === "OverconstrainedError" ? "nomic" : "micerror";
    teardown(); setS({ ...state.s, phase, mic: phase === "denied" ? "blocked" : "error", error: e && e.message }); return;
  }
  if (rt !== r) { stream.getTracks().forEach((t) => t.stop()); return; }
  r.stream = stream;
  const track = stream.getAudioTracks()[0];
  if (track) track.onended = () => { if (rt === r && ["listening", "connecting"].includes(state.s.phase)) fail("miclost", null, { disconnectedAt: r.audioT }); };
  setS({ ...state.s, phase: "connecting", mic: "on", connection: "connecting" });
  r.onReady = async () => {
    try {
      if (!r.ctx || r.ctx.state === "closed") r.ctx = new AudioContext();
      if (r.ctx.state !== "running") r.ctx.resume().catch(() => {});
      await r.ctx.audioWorklet.addModule(new URL("../spike/pcm-worklet.js", import.meta.url));
      if (rt !== r || state.s.phase !== "listening") return; // stopped or failed during setup
      r.source = r.ctx.createMediaStreamSource(stream);
      r.node = new AudioWorkletNode(r.ctx, "pcm-capture");
      const resampler = new Resampler(r.ctx.sampleRate, SAMPLE_RATE);
      r.node.port.onmessage = ({ data }) => {
        r.lastBlockAt = performance.now();
        if (rt !== r || state.s.phase !== "listening") return;
        let sum = 0; for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        r.level = Math.min(1, Math.sqrt(sum / data.length) * 7);
        sendPcm(r, toInt16(resampler.process(data)));
      };
      r.source.connect(r.node);
      // Some browsers (Safari) only run a node that leads to the output; a muted gain keeps it silent.
      const sink = r.ctx.createGain(); sink.gain.value = 0;
      r.node.connect(sink); sink.connect(r.ctx.destination);
      r.captureAt = performance.now();
    } catch (e) { // after Stop the context is closed, so setup may throw; Stop then finishes on its own
      if (rt === r && state.s.phase === "listening") fail("micerror", `audio processing failed: ${e.message}`, { mic: "error" });
    }
  };
  openSocket(state.lang);
}

// Stop: release the microphone at once, stream silence (at least STOP_TAIL_SILENCE_S, longer while the last
// sentence is still being transcribed or checked, up to STOP_DRAIN_MAX_S more), then ask the relay to stop
// and wait for its `stopped` verdict. Only that verdict can say the session was fully checked.
async function stopSession() {
  const r = rt, s = state.s; if (!s || !r) return;
  if (["permission", "connecting", "loading"].includes(s.phase)) {
    teardown();
    setS({ ...s, phase: "stopped", connection: s.connection === "none" ? "none" : "closed", mic: s.source === "live" ? "released" : s.mic, stopInfo: { early: true, confirmed: false, complete: false, problems: [] } });
    return;
  }
  if (s.phase !== "listening" || r.stopping) return;
  r.stopping = true; // a second tap must not start a second tail or send stop twice
  clearInterval(r.streamTimer);
  stopClip();
  try { r.aloud?.stop(); } catch {}
  setS({ ...state.s, phase: "stopping", tail: true });
  if (r.kind === "live") {
    const micOk = await releaseMic(r);
    if (rt !== r) return; // the session failed or ended while the microphone was released
    patchS({ mic: micOk ? "released" : "release-failed" });
  }
  let sent = 0; const tail = STOP_TAIL_SILENCE_S * SAMPLE_RATE, cap = tail + STOP_DRAIN_MAX_S * SAMPLE_RATE;
  r.tailTimer = setInterval(() => {
    if (rt !== r) return clearInterval(r.tailTimer);
    if ((sent < tail || (sent < cap && needsDrain(state.s))) && r.ws.readyState === 1) { sendPcm(r, new Int16Array(1600)); sent += 1600; return; }
    clearInterval(r.tailTimer);
    r.sender.flush();
    if (r.ws.readyState !== 1) { finish(unconfirmedStop("the connection was already closed")); return; }
    r.ws.send(JSON.stringify(stopMessage()));
    record({ type: "stop_sent" }, r.audioT);
    patchS({ tail: false });
    r.stopTimer = setTimeout(() => finish(unconfirmedStop(`no reply within ${STOP_WAIT_MS / 1000} s`)), STOP_WAIT_MS);
  }, 100);
}

function finish(stopInfo) {
  const r = rt; if (!r) return;
  let s = state.s;
  if (stopInfo) s = { ...s, phase: "stopped", connection: "closed", stopInfo };
  s = { ...s, audioT: r.audioT, stopInfo: { ...s.stopInfo, sentAll: !!r.sentAll } };
  teardown();
  setS(s);
}

async function analyseSample() {
  const smp = SAMPLES.find((x) => x.id === state.sampleId);
  teardown();
  state.playback = state.share = null; state.silenced = false;
  const r = rt = { kind: "sample", audioT: 0, log: [], startedAt: new Date().toISOString(), lang: smp.lang, sample: smp.id };
  setS({ ...freshSession("sample"), phase: "loading", sample: smp });
  const o = ensureOut();
  preloadClips(smp.lang); // the warning is spoken in the sample's language
  try {
    const res = await fetch(`/samples/${smp.id}.wav`);
    if (!res.ok) throw new Error(`HTTP ${res.status} — generate it with backend/spike/make_samples.sh`);
    const buf = await o.decodeAudioData(await res.arrayBuffer());
    const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(buf.duration * SAMPLE_RATE)), SAMPLE_RATE);
    const n = off.createBufferSource(); n.buffer = buf; n.connect(off.destination); n.start();
    r.pcm = toInt16((await off.startRendering()).getChannelData(0)); r.buf = buf;
  } catch (e) {
    if (rt !== r) return;
    teardown(); setS({ ...state.s, phase: "loadfail", error: `/samples/${smp.id}.wav — ${e.message || "could not decode audio"}` }); return;
  }
  if (rt !== r) return;
  setS({ ...state.s, phase: "connecting", connection: "connecting", sampleDur: r.buf.duration });
  r.onReady = () => {
    if (state.sampleAloud) { try { const a = o.createBufferSource(); a.buffer = r.buf; a.connect(o.destination); a.start(); r.aloud = a; } catch {} }
    let pos = 0;
    r.streamTimer = setInterval(() => { // real-time pacing, 100 ms frames
      if (rt !== r || r.ws.readyState !== 1) return;
      const end = Math.min(pos + 1600, r.pcm.length);
      sendPcm(r, r.pcm.subarray(pos, end)); pos = end;
      if (end >= r.pcm.length) { clearInterval(r.streamTimer); r.sentAll = true; stopSession(); }
    }, 100);
  };
  openSocket(smp.lang);
}

// ---------------------------------------------------------------- warning clips
function ensureOut() {
  if (!out || out.state === "closed") out = new AudioContext();
  if (out.state !== "running" && out.state !== "closed") out.resume().catch(() => {}); // iOS also reports "interrupted"
  return out;
}
function loadClip(lang, name) {
  const key = `${name}-${lang}`;
  if (!clips[key]) {
    const get = (ext) => fetch(`${CLIP_BASE}/${name}-${lang}.${ext}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.arrayBuffer(); })
      .then((ab) => ensureOut().decodeAudioData(ab));
    clips[key] = get("wav").catch(() => get("mp3")); // the shipped clips are WAV
    clips[key].catch(() => { delete clips[key]; });
  }
  return clips[key];
}
function preloadClips(lang) {
  state.clipStatus[lang] = "loading";
  Promise.all([loadClip(lang, "amber"), loadClip(lang, "red")])
    .then(() => { state.clipStatus[lang] = "ok"; render(); })
    .catch(() => { state.clipStatus[lang] = "missing"; render(); });
}
async function playClip(level, why, lang = (rt && rt.lang) || state.lang) {
  stopClip();
  const token = {}; state.clipTok = token;
  state.playback = { state: "loading", level, why, lang };
  if (why === "test") state.test = { state: "playing" };
  render();
  let buf;
  try { buf = await loadClip(lang, level); }
  catch {
    if (level === "test") { try { buf = await loadClip(lang, "amber"); } catch {} }
    if (!buf) {
      if (state.clipTok !== token) return;
      state.clipTok = null;
      if (level !== "test") state.clipStatus[lang] = "missing";
      state.playback = { state: "error", level, why, lang, msg: `Couldn’t play the warning sound (${CLIP_BASE}/${level}-${lang}).` };
      if (why === "test") state.test = { state: "error", msg: `Test failed: no clip at ${CLIP_BASE}/*-${lang}. Warnings will only appear on screen.` };
      render(); return;
    }
  }
  if (state.clipTok !== token) return;
  const o = ensureOut();
  if (o.state !== "running") await Promise.race([o.resume().catch(() => {}), new Promise((res) => setTimeout(res, 500))]);
  if (state.clipTok !== token) return;
  if (o.state !== "running") { // never play a clip we can't mute for: it would be transcribed as the caller's words
    state.clipTok = null;
    state.playback = { state: "error", level, why, lang, msg: "This device has paused audio output, so the warning couldn’t be spoken." };
    if (why === "test") state.test = { state: "error", msg: "Audio output is paused on this device. Tap the page, check silent mode, and test again." };
    render(); return;
  }
  const r = rt;
  const mute = !!(r && r.kind === "live" && state.s?.phase === "listening" && why !== "replay");
  const t0 = mute ? r.audioT : 0;
  if (mute) { r.muted = true; patchS({ mic: "paused" }); }
  const node = ensureOut().createBufferSource(); node.buffer = buf; node.connect(out.destination);
  const guard = setTimeout(() => done("ended"), (buf.duration + 1) * 1000); // if "ended" never fires
  const done = (how) => {
    clearTimeout(guard);
    if (state.clipTok !== token) return;
    state.clipTok = null; state.clipNode = state.clipDone = null;
    if (mute && rt === r && r.muted) {
      r.muted = false;
      if (state.s?.phase === "listening") state.s = { ...state.s, mic: "on", gaps: [...state.s.gaps, { t: t0, dur: r.audioT - t0, source: "playback" }] };
    }
    state.playback = { state: how, level, why, lang };
    if (why === "test" && how === "ended") state.test = { state: "ask" };
    render();
  };
  node.onended = () => done("ended");
  state.clipNode = node; state.clipDone = done;
  node.start();
  state.playback = { state: "playing", level, why, lang, muted: mute };
  render();
}
function stopClip() {
  const n = state.clipNode, d = state.clipDone;
  if (n) { try { n.onended = null; n.stop(); } catch {} }
  if (d) d("silenced"); else state.clipTok = null;
}

// ---------------------------------------------------------------- replay of a saved session log
function replayState(log, t) {
  let s = { ...freshSession("replay"), phase: "connecting" };
  for (const e of log.events) {
    if (e.t > t) break;
    if (e.m.type === "stop_sent") { s = { ...s, phase: "stopping" }; continue; }
    s = reduce(s, e.m, e.t);
  }
  delete s.newEvent;
  return { ...s, audioT: t };
}
function replayDur(log) { return log.events.length ? Math.max(1, log.events[log.events.length - 1].t) : 1; }
async function loadReplayFile(file) {
  try {
    const log = JSON.parse(await file.text());
    if (log.schema !== LOG_SCHEMA || !Array.isArray(log.events)) throw new Error(`not a ${LOG_SCHEMA} file`);
    state.replay = { ...state.replay, log, t: 0, playing: false, error: null, name: file.name };
  } catch (e) { state.replay = { ...state.replay, log: null, error: `${file.name}: ${e.message}` }; }
  render();
}
function saveLog() {
  const log = state.lastLog; if (!log) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(log, null, 1)], { type: "application/json" }));
  a.download = `callkavach-session-${log.recorded_at.replace(/[:.]/g, "-")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ---------------------------------------------------------------- evaluation report
async function loadReport() {
  if (state.reportState === "loading") return;
  state.reportState = "loading"; render();
  try {
    const r = await fetch(REPORT_URL, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status === 404 ? "no report has been exported to this server yet" : `HTTP ${r.status}`);
    state.report = readReport(await r.json()); state.reportState = "ok";
  } catch (e) { state.reportState = "error"; state.reportErr = String(e.message || e); }
  render();
}

// ---------------------------------------------------------------- actions
const isActive = (s) => !!(s && ["permission", "connecting", "listening", "loading", "stopping"].includes(s.phase));
function setMode(m) {
  if (m === state.mode) return;
  if (isActive(state.s)) { state.confirmSwitch = m; render(); return; }
  doSwitch(m);
}
function doSwitch(m) {
  teardown();
  Object.assign(state, { mode: m, confirmSwitch: null, s: null, test: null, playback: null, share: null });
  state.replay.playing = false;
  history.replaceState(null, "", `#${m}`);
  if (m === "eval" && state.reportState !== "ok") loadReport();
  render();
}
function share(level, tactics) {
  const text = level
    ? `I'm on a call that CallKavach flagged (${level} warning): ${tactics.map((x) => x.label).join("; ")}. Can you call me?`
    : "I'm on a phone call I'm not sure about. Can you call me?";
  if (navigator.share) {
    navigator.share({ title: "CallKavach", text }).then(() => { state.share = { text, status: "Shared. You chose who received it." }; render(); })
      .catch(() => { state.share = { text, status: "Not sent. You can copy this message:" }; render(); });
    return;
  }
  const show = (copied) => { state.share = { text, status: copied ? "Copied. Paste it into a message to someone you trust:" : "Copy this message and send it to someone you trust:" }; render(); };
  Promise.resolve().then(() => navigator.clipboard.writeText(text)).then(() => show(true), () => show(false));
}

const ACTIONS = {
  mode: (m) => setMode(m),
  confirmYes: () => doSwitch(state.confirmSwitch),
  confirmNo: () => { state.confirmSwitch = null; render(); },
  settings: () => { state.settingsOpen = !state.settingsOpen; render(); },
  start: () => startLive(),
  stop: () => stopSession(),
  test: () => { ensureOut(); playClip("test", "test"); },
  testYes: () => { state.test = { state: "yes" }; render(); },
  testNo: () => { state.test = { state: "no" }; render(); },
  silence: () => { stopClip(); if (state.mode === "replay") state.replay.sound = false; else state.silenced = true; render(); },
  unsilence: () => { state.silenced = false; render(); },
  silenceFuture: () => { state.silenced = true; render(); },
  replayClip: (level) => { ensureOut(); playClip(level, "user", state.mode === "replay" ? state.replay.log?.language : undefined); },
  share: () => { const s = currentSession(); share(state.mode === "live" && (s.level === "amber" || s.level === "red") ? s.level : null, s.tactics); },
  pickSample: (id) => { if (!isActive(state.s)) { teardown(); state.sampleId = id; state.s = null; state.playback = null; render(); } },
  analyse: () => (isActive(state.s) ? stopSession() : analyseSample()),
  saveLog: () => saveLog(),
  play: () => {
    const rp = state.replay; if (!rp.log) return;
    ensureOut();
    if (rp.playing) { stopClip(); rp.playing = false; } else { rp.playing = true; if (rp.t >= replayDur(rp.log)) rp.t = 0; }
    render();
  },
  restart: () => { stopClip(); Object.assign(state.replay, { t: 0, playing: !!state.replay.log }); render(); },
  speed: () => { const rp = state.replay; rp.speed = rp.speed === 1 ? 2 : rp.speed === 2 ? 4 : 1; render(); },
  retryReport: () => { state.reportState = "idle"; loadReport(); },
};

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.disabled) return;
  ACTIONS[el.dataset.act]?.(el.dataset.arg);
});
document.addEventListener("change", (e) => {
  const el = e.target;
  if (el.id === "lang") {
    state.lang = el.value; store("callkavach.lang", el.value); state.test = null;
    if (state.s?.source === "live" && isActive(state.s)) preloadClips(el.value);
    render();
  } else if (el.id === "autoSpeak") { state.autoSpeak = el.checked; store("callkavach.autoSpeak", el.checked ? "1" : "0"); render(); }
  else if (el.id === "sampleAloud") { state.sampleAloud = el.checked; }
  else if (el.id === "replaySound") { state.replay.sound = el.checked; if (!el.checked) stopClip(); render(); }
  else if (el.id === "replayFile" && el.files[0]) loadReplayFile(el.files[0]);
});
document.addEventListener("input", (e) => {
  if (e.target.id === "scrub" && state.replay.log) { stopClip(); state.replay.t = parseFloat(e.target.value) || 0; render(); }
});
window.addEventListener("beforeunload", () => teardown());

// ---------------------------------------------------------------- ticker
const MIC_STALL_MS = 4000; // no audio blocks for this long while listening: the microphone has stopped
const AUTO_STOP_AUDIO_S = 870; // the relay ends a session at 900 s of audio; stop cleanly before that
let lastTick = performance.now();
setInterval(() => {
  const t = performance.now(), dt = Math.min(0.5, (t - lastTick) / 1000); lastTick = t;
  let dirty = false;
  if (rt && state.s?.phase === "listening") {
    // A locked screen or a backgrounded tab can stop capture without any error event.
    // Two stale ticks in a row, and never while a warning clip plays (iOS may pause capture for it).
    const stale = rt.kind === "live" && rt.captureAt && !state.clipNode && t - (rt.lastBlockAt || rt.captureAt) > MIC_STALL_MS;
    rt.staleTicks = stale ? (rt.staleTicks || 0) + 1 : 0;
    if (rt.staleTicks >= 2) { fail("miclost", null, { disconnectedAt: rt.audioT }); return; }
    if (rt.audioT >= AUTO_STOP_AUDIO_S) { state.s = { ...state.s, autoStopped: true }; stopSession(); }
  }
  if (rt && state.s && ["listening", "stopping"].includes(state.s.phase)) {
    state.s = { ...state.s, audioT: rt.audioT, backlog: !!rt.backlog }; state.meter = rt.level || 0; dirty = true;
  }
  const rp = state.replay;
  if (rp.playing && state.mode === "replay" && rp.log) {
    const dur = replayDur(rp.log), prev = rp.t;
    rp.t = Math.min(dur, rp.t + dt * rp.speed);
    if (rp.t >= dur) rp.playing = false;
    if (rp.sound) {
      const before = replayState(rp.log, prev).events.length, after = replayState(rp.log, rp.t);
      if (after.events.length > before) playClip(after.events[after.events.length - 1].level, "replay", rp.log.language);
    }
    dirty = true;
  }
  if (dirty) render();
}, 200);

// ---------------------------------------------------------------- view
function currentSession() {
  if (state.mode === "replay") return state.replay.log ? replayState(state.replay.log, state.replay.t) : freshSession("replay");
  if (state.s && state.s.source === state.mode) return state.s;
  return { ...freshSession(state.mode), sample: state.mode === "sample" ? SAMPLES.find((x) => x.id === state.sampleId) : null };
}

const FAILS = ["denied", "nomic", "unsupported", "micerror", "unreachable", "disconnected", "miclost", "loadfail", "servererror", "accessdenied", "quota"];

function icon(kind, ink) {
  if (kind === "listening") return `<span style="position:relative;width:20px;height:20px;display:block"><span style="position:absolute;inset:0;border-radius:50%;background:${ink};animation:ckPulse 1.8s ease-out infinite"></span><span style="position:absolute;inset:0;border-radius:50%;background:${ink}"></span></span>`;
  if (kind === "busy") return `<span style="width:34px;height:34px;border-radius:50%;border:4px solid ${ink};border-right-color:transparent;display:block;animation:ckSpin .9s linear infinite"></span>`;
  if (kind === "alert") return `<span style="width:46px;height:46px;border-radius:50%;border:3px solid ${ink};display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:800;line-height:1">!</span>`;
  if (kind === "fail") return `<span style="width:44px;height:44px;border-radius:8px;border:3px solid ${ink};display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:800;line-height:1">×</span>`;
  return "";
}

function warningView(s) {
  const ph = s.phase, src = s.source, t = s.audioT;
  const busy = ["permission", "connecting", "loading", "stopping"].includes(ph);
  const smp = s.sample, log = state.replay.log;
  const lname = langByCode(state.lang).name;
  const failCopy = {
    denied: ["Microphone blocked — not listening", "CallKavach cannot hear the call. Allow microphone access for this site in your browser settings, then tap Try again."],
    nomic: ["No microphone found — not listening", "Connect or switch on a microphone on this device, then tap Try again."],
    unsupported: ["This browser can’t use the microphone", "Open CallKavach in a recent Chrome, Edge, Firefox or Safari, over https."],
    micerror: ["Microphone couldn’t start — not listening", s.error || "Another app may be using it. Close it and tap Try again."],
    unreachable: ["Can’t reach the analysis server — not listening", `Nothing is being transcribed or checked (${s.error || "no connection"}). Check the internet connection and try again.`],
    disconnected: ["Disconnected — not listening", `The connection dropped at ${fmt(s.disconnectedAt)} (${s.error || "unknown reason"}). Nothing after that was heard or checked.`],
    miclost: ["Microphone stopped — not listening", `The microphone stopped delivering audio at ${fmt(s.disconnectedAt)}: it was switched off or unplugged, the screen locked, or another app took it. Nothing after that was heard or checked. Keep this screen open and unlocked while listening.`],
    loadfail: ["Couldn’t load the sample audio", `${s.error}. Nothing was analysed.`],
    servererror: ["The server ended the session — not listening", `${s.error}. Nothing after this is being checked.`],
    accessdenied: ["Server access denied — not listening", "This server rejected the session. Nothing was sent for transcription."],
    quota: ["Session limit reached — not listening", `${s.error} Nothing was sent for transcription.`],
  };
  let tone = "neutral", ic = null, headline = "", body = "";
  const h = headlineFor(s);
  if (FAILS.includes(ph)) { tone = "failure"; ic = "fail"; [headline, body] = failCopy[ph]; }
  else if (h) { ({ tone, headline, body } = h); ic = tone === "amber" || tone === "red" ? "alert" : tone === "failure" ? "fail" : null; }
  else if (ph === "idle") {
    if (src === "live") { headline = "Not listening yet"; body = "Put the doubtful call on speakerphone and keep this device close to it. Then tap Start listening."; }
    else if (src === "sample") { headline = "Choose a sample to analyse"; body = "The sample’s audio goes through the same speech-to-text and detector as the microphone would."; }
    else { headline = log ? "Saved session — press Play" : "Load a saved session log"; body = log ? `Plays back the events saved on ${new Date(log.recorded_at).toLocaleString("en-IN")}. Nothing is listening and nothing is being analysed.` : "Choose a session log saved from Live or Sample mode. Nothing is listening and nothing is being analysed."; }
  } else if (busy && ph !== "stopping") {
    ic = "busy";
    if (ph === "permission") { headline = "Waiting for microphone permission"; body = "Your browser should be asking now. Choose Allow so CallKavach can hear the speakerphone."; }
    else if (ph === "loading") { headline = "Loading sample audio…"; body = `/samples/${smp.id}.wav`; }
    else { headline = "Connecting — not listening yet"; body = src === "live" ? "Microphone is on. Waiting for the analysis server to accept audio." : src === "sample" ? "Waiting for the analysis server to accept the sample." : "Recorded: connecting."; }
  } else if (ph === "listening") {
    ic = "listening";
    if (s.analysis === "waiting") { headline = "Listening — no warning yet"; body = "Words are checked once each sentence is transcribed. “No warning yet” does not mean the call is safe."; }
    else if (src === "sample") { headline = "Analysing sample — no warning yet"; body = "The sample is streamed in real time through the same speech-to-text and detector as the microphone."; }
    else { headline = "No warning yet"; body = "“No warning yet” does not mean the call is safe. Never share an OTP, PIN or password with a caller."; }
  } else if (ph === "stopping") {
    ic = "busy"; headline = src === "sample" ? "Finishing analysis…" : "Stopping…";
    body = s.tail ? `${src === "live" ? "Microphone released. " : "All audio sent. "}Sending silence until the last words are transcribed and checked (up to ${STOP_TAIL_SILENCE_S + STOP_DRAIN_MAX_S} s).` : `Waiting up to ${STOP_WAIT_MS / 1000} s for the server to confirm the last words were checked.`;
  } else if (ph === "stopped") { headline = "Stopped"; body = ""; }
  const c = TONES[tone], ink = c.ink;
  const pats = [c.pattern, src === "replay" ? (tone === "neutral" ? "repeating-linear-gradient(-45deg,rgba(91,59,158,.08) 0 14px,transparent 14px 28px)" : "repeating-linear-gradient(-45deg,rgba(255,255,255,.13) 0 14px,transparent 14px 28px)") : ""].filter(Boolean);
  const modeColor = MODE_COLOR[src];
  // Ticking values (the clock) are placeholders filled in by updateLive(), so this card, and its buttons,
  // are only rebuilt when something actually changes, never five times a second.
  const clock = '<span data-live="clock"></span>';
  const kicker = src === "live" ? (ph === "listening" ? `Listening · ${clock}` : ph === "stopping" ? "Stopping" : ph === "stopped" ? "Stopped · not listening" : busy ? "Not listening yet" : "Not listening")
    : src === "sample" ? `${esc(smp ? smp.title : "No sample")} · ${ph === "listening" ? clock : esc(ph)}` : log ? `Recording time ${clock} of ${fmt(replayDur(log))}` : "No recording loaded";
  const band = src === "replay" && log ? `RECORDED ${new Date(log.recorded_at).toLocaleString("en-IN")} — this is not happening now. Nothing is listening.`
    : src === "sample" && smp && ph !== "idle" ? `SAMPLE: “${smp.title}” (${smp.kind}, ${smp.langName}) — not a live call.` : "";
  const running = ["listening", "stopping", "stopped"].includes(ph);
  const knowable = running && !FAILS.includes(ph) && s.analysis !== "unavailable" && s.level !== "unknown" && !(ph === "stopped" && s.stopInfo && !s.stopInfo.complete && s.level === "none");
  const cur = s.level === "amber" || s.level === "red";

  let html = `<section class="warn" style="background-color:${c.bg};background-image:${pats.join(",") || "none"};color:${ink};border:${src === "live" ? `2px solid ${c.border}` : `3px dashed ${modeColor}`}">
    <div class="row-between"><div class="row"><span class="tag" style="background:${modeColor};color:#fff;border:1.5px solid ${tone === "neutral" ? modeColor : "#fff"}">${src.toUpperCase()}</span><span class="mono" style="font-size:14px;font-weight:600">${kicker}</span></div>`;
  if (knowable) {
    html += `<div role="group" aria-label="Warning level from the backend" class="row" style="gap:4px;font-size:13px;font-weight:700"><span style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;padding-right:4px">${ph === "stopped" ? "Last level" : "Backend level"}</span>`;
    for (const [k, label] of [["none", ph === "stopped" ? "No warning" : "No warning yet"], ["amber", "Amber · careful"], ["red", "Red · stop"]]) {
      const on = k === s.level;
      html += `<span style="padding:5px 9px;border-radius:6px;border:1.5px ${on ? "solid" : "dashed"} currentColor;background:${on ? ink : "transparent"};color:${on ? c.bg : ink}">${label}</span>`;
    }
    html += "</div>";
  } else {
    html += `<span style="font-size:13px;font-weight:700;padding:5px 10px;border-radius:6px;border:1.5px dashed currentColor">${ph === "idle" || busy ? "Level: not checking yet" : ph === "listening" ? "Level unknown — words are not being checked" : "Level unknown — not everything was checked"}</span>`;
  }
  html += "</div>";
  if (band) html += `<div style="padding:9px 12px;border-radius:8px;background:${modeColor};color:#fff;font-size:15px;font-weight:700;border:1.5px solid #fff">${esc(band)}</div>`;
  html += `<div style="display:flex;gap:16px;align-items:flex-start">${ic ? `<div style="flex:none;width:48px;height:48px;display:flex;align-items:center;justify-content:center;margin-top:2px">${icon(ic, ink)}</div>` : ""}
    <div style="min-width:0;display:flex;flex-direction:column;gap:8px"><h2 class="headline">${esc(headline)}</h2>${body ? `<p class="lede">${esc(body)}</p>` : ""}</div></div>`;
  if (cur) { // the reviewed spoken-warning text, readable even with the sound off
    const wl = src === "replay" && log ? log.language : src === "sample" && smp ? smp.lang : state.lang;
    html += `<div style="display:flex;flex-direction:column;gap:4px;padding:12px 14px;border-radius:12px;background:${c.quoteBg}"><span class="eyebrow">Warning · ${esc(langByCode(wl).name)}</span><p lang="${esc(wl)}" style="margin:0;font-size:clamp(20px,2.4vw,24px);line-height:1.45;font-weight:700">${esc(WARNING_COPY[`${s.level}-${wl}`] || "")}</p></div>`;
  }

  if (s.tactics.length && (cur || s.events.length)) {
    const first = s.events[s.events.length - 1];
    html += `<div style="display:flex;flex-direction:column;gap:10px;padding-top:14px;border-top:1.5px solid ${c.rule}">
      <div class="row" style="gap:4px 12px;align-items:baseline"><span class="eyebrow">${cur && !FAILS.includes(ph) ? "What it noticed" : `Earlier warning (${first ? first.level : s.level})`}</span>${s.reason ? `<span style="font-size:15px;font-weight:700">Rule: ${esc(s.reason)}</span>` : ""}</div>`;
    for (const x of s.tactics) {
      html += `<div style="display:flex;flex-direction:column;gap:6px"><span style="font-size:19px;font-weight:800;text-wrap:pretty">${esc(x.label)}</span>`;
      for (const q of x.evidence) html += `<figure style="margin:0;padding:12px 14px;border-radius:10px;background:${c.quoteBg};display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;align-items:baseline"><span class="mono" style="font-size:14px;font-weight:700">${fmt(q.t)}</span><blockquote style="margin:0;font-size:18px;line-height:1.4;font-style:italic">“${esc(q.quote)}”</blockquote></figure>`;
      html += "</div>";
    }
    if (cur) html += `<p style="margin:0;font-size:18px;line-height:1.4"><strong style="font-weight:800">What to do: </strong>${s.level === "red" ? "Do not share any OTP, PIN or password and do not send money. You can hang up now." : "Don’t rush. You can hang up and call the number printed on your bank card yourself."}</p>`;
    if (s.events.length > 1) html += `<div style="display:flex;flex-direction:column;gap:4px;font-size:15px"><span style="font-weight:700">Warnings in this session</span>${s.events.map((e) => `<span><span class="mono" style="font-weight:700">${fmt(e.t)}</span> · ${e.level === "red" ? "Red" : "Amber"}: ${esc(e.reason || "")}</span>`).join("")}</div>`;
    html += "</div>";
  }

  const N = [];
  const cs = state.clipStatus[state.lang];
  if (src === "live" && cs === "missing" && ph !== "idle") N.push(["SOUND", `Spoken warnings unavailable: the ${lname} clips couldn’t load. Warnings will only appear on screen.`]);
  if (src !== "replay" && state.silenced) N.push(["SOUND", "Spoken warnings are silenced for this session."]);
  if (ph === "listening" && src === "live" && t - (s.lastWordsAt ?? 0) > 15) N.push(["QUIET", "No words transcribed for over 15 s. Is the call on speaker and close to this device?"]);
  if (s.backlog) N.push(["NETWORK", "The network is slow. Audio is queued, so warnings may arrive late."]);
  if (ph === "listening" && s.analysis === "ok" && s.unanalysed > 0) N.push(["ANALYSIS", `${s.unanalysed} recent segment${s.unanalysed > 1 ? "s are" : " is"} still being checked.`]);
  s.gaps.filter((g) => g.source !== "playback").slice(-2).forEach((g) => N.push(["GAP", `Audio gap at ${fmt(g.t)} (${g.dur.toFixed(1)} s, ${g.source === "client" ? "not sent — connection too slow" : "server could not keep up"}). That part was not heard or checked.`]));
  if (s.autoStopped) N.push(["LIMIT", "Stopped automatically at the 15-minute session limit. Start a new session to keep listening."]);
  if (ph === "stopped" && s.stopInfo) s.stopInfo.problems.forEach((p) => N.push([p.tag, p.text]));
  if (N.length) html += `<div style="display:flex;flex-direction:column;gap:8px">${N.map(([tag, text]) => `<div style="display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;align-items:baseline;padding:10px 12px;border-radius:10px;border:1.5px dashed currentColor;font-size:16px;line-height:1.4"><span class="mono" style="font-size:12px;font-weight:700;letter-spacing:.08em;padding:2px 6px;border-radius:4px;background:${ink};color:${c.bg}">${esc(tag)}</span><span>${esc(text)}</span></div>`).join("")}</div>`;

  const pb = state.playback;
  let playLine = "", playTag = "SOUND";
  if (pb && pb.why !== "test") {
    if (pb.state === "playing") playLine = `Speaking the ${pb.level} warning in ${langByCode(pb.lang).name}${pb.muted ? " · silence is sent meanwhile so the warning isn’t transcribed" : ""}`;
    else if (pb.state === "loading") playLine = "Loading the warning sound…";
    else if (pb.state === "error") { playTag = "NO SOUND"; playLine = `${pb.msg} Read the warning on screen.`; }
  }
  if (playLine) html += `<div class="row" style="padding:12px 14px;border-radius:12px;background:${c.quoteBg};font-size:16px;font-weight:700"><span class="mono" style="font-size:12px;letter-spacing:.08em;padding:3px 7px;border-radius:4px;border:1.5px solid currentColor">${playTag}</span><span style="flex:1;min-width:200px">${esc(playLine)}</span></div>`;

  const playing = pb && pb.state === "playing" && pb.why !== "test";
  const wb = [];
  if (cur) {
    if (playing) wb.push(["silence", "Silence warning", ""]);
    else wb.push(["replayClip", "Replay warning sound", s.level]);
    if (src !== "replay" && state.silenced) wb.push(["unsilence", "Turn warning sound back on", ""]);
    else if (src !== "replay" && !playing && isActive(s)) wb.push(["silenceFuture", "Silence future warnings", ""]);
  }
  if (wb.length) html += `<div class="row" style="gap:8px">${wb.map(([a, l, arg]) => `<button class="btn" data-act="${a}" data-arg="${arg}">${l}</button>`).join("")}</div>`;

  const ts = state.test;
  if (src === "live" && ts) {
    const line = ts.state === "playing" ? `Playing the ${lname} test clip…` : ts.state === "ask" ? "Did you hear it clearly from where you’ll be sitting?" : ts.state === "yes" ? "Sound works. Keep this device’s volume up during the call." : ts.state === "no" ? "Turn up this device’s volume, switch off silent mode, and keep it close. Then test again." : ts.msg;
    html += `<div class="row" style="padding:12px 14px;border-radius:12px;border:1.5px solid currentColor;font-size:16px"><span class="mono" style="font-size:12px;font-weight:700;letter-spacing:.08em">SOUND TEST</span><span style="flex:1;min-width:200px">${esc(line)}</span>${ts.state === "ask" ? `<div class="row" style="gap:8px"><button class="btn btn-sm" data-act="testYes">Yes, clearly</button><button class="btn btn-sm" data-act="testNo">No</button></div>` : ""}</div>`;
  }

  if (src === "live") {
    let p;
    if (ph === "listening") p = ["stop", "■", "Stop listening", false];
    else if (ph === "permission" || ph === "connecting") p = ["stop", "■", "Cancel", false];
    else if (ph === "stopping") p = ["", "■", "Stopping…", true];
    else if (["denied", "nomic", "unsupported", "micerror"].includes(ph)) p = ["start", "●", "Try again", false];
    else if (ph === "idle") p = ["start", "●", "Start listening", false];
    else p = ["start", "●", "Start again — new session", false];
    const meter = (s.mic === "on" || s.mic === "paused") && running;
    html += `<div class="row" style="gap:10px;padding-top:4px">
      <button data-act="${p[0]}" ${p[3] ? "disabled" : ""} class="btn-primary" style="background:${c.btnBg};color:${c.btnInk}"><span style="font-size:14px">${p[1]}</span>${p[2]}</button>
      <button class="btn" data-act="test" ${ph === "stopping" || ph === "listening" ? "disabled" : ""}>Test warning sound</button>
      ${ph === "idle" ? `<span style="flex-basis:100%;font-size:14px">On an iPhone, switch off silent mode or warnings will only appear on screen.</span>` : ""}
      ${ph === "stopped" && state.lastLog ? `<button class="btn" data-act="saveLog">Save session log</button>` : ""}
      ${meter ? `<div class="row" style="gap:8px;font-size:14px;font-weight:700;margin-left:auto"><span>${s.mic === "paused" ? "Mic muted" : "Mic level"}</span><div aria-hidden="true" style="width:110px;height:10px;border-radius:5px;border:1.5px solid currentColor;overflow:hidden"><div data-live="meter" style="height:100%;width:0%;background:currentColor"></div></div></div>` : ""}
    </div>`;
  }
  return html + "</section>";
}

function healthRows(s) {
  const mk = (name, value, detail, k) => {
    const m = { ok: ["#17191E", "1.5px solid #17191E", "3px"], wait: ["transparent", "2px dashed #17191E", "50%"], bad: ["repeating-linear-gradient(135deg,#17191E 0 3px,#8A8F99 3px 5px)", "1.5px solid #17191E", "3px"], off: ["transparent", "1.5px solid #17191E", "3px"] }[k];
    return `<div class="hrow"><span style="margin-top:3px;width:16px;height:16px;border-radius:${m[2]};border:${m[1]};background:${m[0]}"></span><span style="font-weight:700;font-size:16px">${esc(name)}</span><span style="display:flex;flex-direction:column;gap:2px;font-size:16px;min-width:0"><span style="font-weight:${k === "bad" ? 800 : 500}">${esc(value)}</span>${detail ? `<span style="font-size:14px;color:#4A4F59;overflow-wrap:anywhere">${esc(detail)}</span>` : ""}</span></div>`;
  };
  const ph = s.phase, src = s.source, t = s.audioT;
  if (src === "replay") return [
    mk("Source", state.replay.log ? "Saved session log" : "No file loaded", state.replay.name || "", state.replay.log ? "ok" : "off"),
    mk("Microphone", "Not running — replay", "Nothing is being heard", "off"),
    mk("Speech-to-text", "Not running", "Showing saved text", "off"),
    mk("Detector", "Not running", "Showing saved decisions", "off"),
  ].join("");
  const rows = [];
  if (src === "live") {
    const micMap = { off: ["Off", "", "off"], asking: ["Asking permission", "", "wait"], blocked: ["Blocked by the browser", "Allow the microphone for this site", "bad"], error: ["Couldn’t start", s.error || "", "bad"], unsupported: ["Not supported here", "", "bad"], on: ["On", "Hearing the speakerphone", "ok"], paused: ["Muted", "While the warning plays — silence is sent instead", "wait"], released: ["Released", "All microphone tracks stopped", "off"], "release-failed": ["Still held", "Close this tab to release it", "bad"] };
    let m = micMap[s.mic] || micMap.off;
    if (ph === "miclost") m = ["Stopped unexpectedly", `At ${fmt(s.disconnectedAt)}`, "bad"];
    rows.push(mk("Microphone", ...m));
  } else {
    const ok = ph !== "loadfail";
    rows.push(mk("Audio source", ok ? "Sample file" : "Couldn’t load file", s.sample ? `/samples/${s.sample.id}.wav · ${s.sample.kind}` : "", ph === "idle" ? "off" : ok ? "ok" : "bad"));
    rows.push(mk("Microphone", "Not used", "Sample mode never uses the microphone", "off"));
  }
  const connMap = { none: ["Not connected", "", "off"], connecting: ["Connecting…", "", "wait"], "open-waiting": ["Reached — waiting for the server", "", "wait"], open: ["Connected", "", "ok"], closed: ["Closed", "", "off"], lost: ["Dropped", `At ${fmt(s.disconnectedAt)} · ${s.error || ""}`, "bad"], unreachable: ["Can’t reach server", s.error || "", "bad"] };
  const cm = connMap[s.connection] || connMap.none;
  rows.push(mk("Server connection", cm[0], cm[1] || (s.connection !== "none" ? "/ws/audio on this server" : ""), ph === "servererror" ? "bad" : cm[2]));
  if (ph === "listening") {
    const since = t - (s.lastWordsAt ?? 0);
    if (s.speaking) rows.push(mk("Speech-to-text", "Hearing speech", "The sentence is transcribed when it ends", "ok"));
    else if (s.lastWordsAt == null) rows.push(mk("Speech-to-text", "Waiting for speech", "", "wait"));
    else if (since > 15) rows.push(mk("Speech-to-text", `No words for ${Math.round(since)} s`, "Check the speakerphone volume", "wait"));
    else rows.push(mk("Speech-to-text", "Transcribing", `Last words ${Math.max(0, Math.round(since))} s ago`, "ok"));
    const am = { waiting: ["Waiting for the first sentence", "", "wait"], ok: [s.unanalysed ? "Checking" : "Up to date", `${s.analysed} of ${s.analysed + s.unanalysed} segment(s) checked · ${s.calls} call(s)${s.lastLatency != null ? ` · last took ${s.lastLatency.toFixed(1)} s` : ""}`, s.unanalysed ? "wait" : "ok"], unavailable: ["Unavailable", s.analysisError || "Words are not being checked", "bad"] }[s.analysis];
    rows.push(mk("Scam-tactic analysis", ...am));
  } else if (ph === "stopping") {
    rows.push(mk("Speech-to-text", "Finishing", "", "wait"));
    rows.push(mk("Scam-tactic analysis", "Finishing", `${s.analysed} segment(s) checked so far`, "wait"));
  } else if (ph === "stopped" && s.stopInfo && !s.stopInfo.early) {
    const si = s.stopInfo;
    rows.push(mk("Speech-to-text", si.transcription === "complete" ? "Complete" : si.confirmed ? "Incomplete" : "Not confirmed", si.segments != null ? `${si.segments} segment(s)` : "", si.transcription === "complete" ? "off" : "bad"));
    rows.push(mk("Scam-tactic analysis", si.cutOff ? "Cut off at Stop" : si.analysisStatus === "complete" ? "Complete" : si.analysisStatus ? `Status: ${si.analysisStatus}` : "Not confirmed", `${s.analysed} segment(s) checked · ${s.calls} call(s)${s.cost ? ` · reported cost ₹${s.cost.toFixed(2)}` : ""}`, si.analysisStatus === "complete" ? "off" : "bad"));
  } else {
    const bad = ["unreachable", "disconnected", "miclost", "servererror", "accessdenied", "quota"].includes(ph);
    rows.push(mk("Speech-to-text", "Not running", "", bad ? "bad" : "off"));
    rows.push(mk("Scam-tactic analysis", "Not running", bad ? "Nothing is being checked" : "", bad ? "bad" : "off"));
  }
  if (src === "live") {
    const ln = langByCode(state.lang).name, st = state.clipStatus[state.lang];
    if (state.silenced) rows.push(mk("Spoken warning", "Silenced", "For this session", "wait"));
    else if (st === "ok") rows.push(mk("Spoken warning", "Ready", `${ln} amber and red clips loaded`, "ok"));
    else if (st === "missing") rows.push(mk("Spoken warning", "Clips missing", `${CLIP_BASE}/*-${state.lang} · on-screen only`, "bad"));
    else if (st === "loading") rows.push(mk("Spoken warning", "Loading…", ln, "wait"));
    else rows.push(mk("Spoken warning", "Not loaded yet", `Loads when you tap Start (${ln})`, "off"));
  }
  return rows.join("");
}

function transcriptView(s) {
  const lv = {};
  for (const x of s.tactics) for (const q of x.evidence) if (q.segmentId) lv[q.segmentId] = s.level === "red" ? "red" : "amber";
  const items = [];
  s.segs.forEach((g, i) => {
    const l = lv[g.id];
    const checked = i < s.analysed;
    items.push([g.t, `<span style="font-size:17px;line-height:1.45;background:${l === "red" ? "#F6D3CF" : l === "amber" ? "#FBE3A0" : "transparent"};padding:0 2px">${esc(g.text)}</span>${l ? `<span class="evtag" style="background:${l === "red" ? "#B3261E" : "#F5C242"};color:${l === "red" ? "#fff" : "#1C1405"}">EVIDENCE</span>` : ""}${!checked && s.source !== "replay" && s.phase === "stopped" ? `<span class="evtag" style="border:1.5px solid #17191E">NOT CHECKED</span>` : ""}`]);
  });
  if (s.speaking && s.phase === "listening") items.push([s.audioT, `<span class="prov">Speech detected — transcribing when the sentence ends…</span>`]);
  for (const g of s.gaps) {
    if (g.source === "playback") items.push([g.t, `<div class="gap" style="border-style:dashed">Muted ${fmt(g.t)}–${fmt(g.t + g.dur)} while the warning played. Speech here was not analysed.</div>`]);
    else items.push([g.t, `<div class="gap">Audio gap at ${fmt(g.t)} · ${g.dur.toFixed(1)} s ${g.source === "client" ? "not sent (connection too slow)" : "dropped by the server"}. Not heard, not checked.</div>`]);
  }
  for (const e of s.events) items.push([e.t + 0.001, `<div class="evline" style="background:${e.level === "red" ? "#B3261E" : "#F5C242"};color:${e.level === "red" ? "#fff" : "#1C1405"}">${e.level === "red" ? "Red" : "Amber"} warning raised · ${esc(e.reason || "")}</div>`]);
  if (s.phase === "disconnected" || s.phase === "miclost") items.push([1e7, `<div class="gap">${s.phase === "miclost" ? "Microphone stopped" : "Disconnected"} at ${fmt(s.disconnectedAt)}. Nothing after this was heard or checked.</div>`]);
  if (s.phase === "stopped" && s.stopInfo && !s.stopInfo.early) items.push([1e7, s.stopInfo.complete ? `<div class="endline">Stopped at ${fmt(s.audioT)} · everything transcribed was checked.</div>` : `<div class="gap">Stopped at ${fmt(s.audioT)} · not everything was transcribed or checked.</div>`]);
  items.sort((a, b) => a[0] - b[0]);
  const empty = s.phase === "idle" ? (s.source === "replay" ? "Press Play to show the saved transcript." : "The transcript appears here once listening starts. Each sentence appears when it ends.") : ["listening", "connecting", "permission", "loading"].includes(s.phase) ? "No words heard yet." : "No words were transcribed.";
  return items.length ? items.map(([t, h]) => `<div class="tline"><span class="mono" style="font-size:13px;font-weight:700;color:#3B3F47">${t >= 1e6 ? fmt(s.audioT) : fmt(t)}</span><div style="min-width:0">${h}</div></div>`).join("") : `<p style="margin:0;padding:18px 0;font-size:16px;color:#4A4F59">${empty}</p>`;
}

function sampleResult(s) {
  if (s.source !== "sample" || s.phase !== "stopped" || !s.sample || !s.stopInfo) return "";
  const smp = s.sample, si = s.stopInfo;
  let inner;
  if (!si.complete || !si.sentAll) {
    const why = si.early || !si.sentAll ? "analysis was stopped before the whole sample was sent" : si.problems.map((p) => p.text.replace(/\.$/, "")).join("; ");
    inner = `<h3 style="margin:0;font-size:26px;line-height:1.15;font-weight:800">No comparison with the label: ${esc(why)}.</h3><p class="note">The label stays hidden because the result is incomplete. Run the sample again to compare.</p>`;
  } else {
    const first = s.events[0], red = s.events.find((e) => e.level === "red");
    const outcome = smp.label === "scam" ? (first ? `Warned on this scam sample (${first.level} at ${fmt(first.t)}).` : "Missed: no warning was raised on this scam sample.") : (first ? `False alarm: ${first.level} raised on a genuine sample.` : "No false alarm on this genuine sample.");
    const rows = [["Label", `${smp.label === "scam" ? "Scam" : "Genuine"} · ${smp.kind} · ${smp.langName}`], ["First dangerous ask", "Not labelled for this sample, so no lead time is computed"], ["First backend warning", first ? `${first.level === "red" ? "Red" : "Amber"} at ${fmt(first.t)} — ${first.reason || ""}` : "None"]];
    if (red && red !== first) rows.push(["First red", `${fmt(red.t)} — ${red.reason || ""}`]);
    rows.push(["Pipeline", `${s.segs.length} segment(s) · ${s.calls} analysis call(s)${s.cost ? ` · reported cost ₹${s.cost.toFixed(2)}` : ""}`]);
    const dur = s.audioT || 1, pct = (t) => Math.max(0, Math.min(99.4, (t / dur) * 100)).toFixed(2);
    inner = `<h3 style="margin:0;font-size:26px;line-height:1.15;font-weight:800">${esc(outcome)}</h3>
      <dl style="margin:0;display:grid;grid-template-columns:minmax(0,190px) minmax(0,1fr);gap:8px 14px;font-size:16px;line-height:1.4">${rows.map(([k, v]) => `<dt style="font-weight:700">${k}</dt><dd style="margin:0">${esc(v)}</dd>`).join("")}</dl>
      <div style="position:relative;height:30px;border-radius:6px;background:#FBF9F4;border:1.5px solid #2747A6" aria-hidden="true">${s.events.map((e) => `<span style="position:absolute;top:-4px;bottom:-4px;left:${pct(e.t)}%;width:4px;background:${e.level === "red" ? "#B3261E" : "#E0A400"};border-radius:2px"></span>`).join("")}</div>
      <div class="mono" style="display:flex;justify-content:space-between;font-size:13px"><span>0:00</span><span>${fmt(dur)}</span></div>
      <p class="note">One synthetic sample is a smoke check, not an accuracy measurement. Warning times are when the event reached this page, measured in seconds of audio sent.</p>`;
  }
  return `<section style="background:#E3E8F6;border:3px dashed #2747A6;border-radius:18px;padding:20px 22px;display:flex;flex-direction:column;gap:14px"><div><span class="tag" style="background:#2747A6;color:#fff">SAMPLE RESULT · COMPARED WITH ITS LABEL</span></div>${inner}</section>`;
}

function samplePicker(s) {
  const busy = isActive(state.s);
  return `<section class="card" style="border:3px dashed #2747A6"><div class="card-h"><h3 class="t">Choose a sample</h3><span class="sub">Scam / genuine labels stay hidden until analysis finishes</span></div>
    <div role="radiogroup" style="display:flex;flex-direction:column;gap:8px">${SAMPLES.map((sm) => { const sel = sm.id === state.sampleId; return `<button role="radio" aria-checked="${sel}" data-act="pickSample" data-arg="${sm.id}" ${busy ? "disabled" : ""} class="pick" style="border-color:${sel ? "#2747A6" : "#CFC8B8"};background:${sel ? "#E3E8F6" : "#fff"}"><span class="dot" style="border-color:#2747A6"><span style="background:${sel ? "#2747A6" : "transparent"}"></span></span><span style="display:flex;flex-direction:column;gap:2px;min-width:0"><span style="font-weight:700;font-size:17px">${esc(sm.title)}</span><span class="sub">${esc(sm.langName)}</span></span><span class="mono kind">${sm.kind.toUpperCase()}</span></button>`; }).join("")}</div>
    <div class="row" style="gap:10px"><button data-act="analyse" ${busy && s.phase === "stopping" ? "disabled" : ""} class="btn-primary" style="background:#2747A6;color:#fff">${busy ? (s.phase === "stopping" ? "Finishing…" : "Stop analysis") : s.phase !== "idle" ? "Analyse again" : "Analyse this sample"}</button>
    <label class="row" style="gap:8px;font-size:15px"><input type="checkbox" id="sampleAloud" ${state.sampleAloud ? "checked" : ""} ${busy ? "disabled" : ""} style="width:20px;height:20px;accent-color:#2747A6">Play the sample aloud while it’s analysed</label>
    ${s.phase === "stopped" && state.lastLog ? `<button class="btn" style="color:#2747A6" data-act="saveLog">Save session log</button>` : ""}</div>
    ${["listening", "stopping", "stopped"].includes(s.phase) && s.sampleDur ? `<div style="display:flex;flex-direction:column;gap:6px"><div style="height:10px;border-radius:5px;background:#D9DFEF;overflow:hidden"><div data-live="sampleBar" style="height:100%;width:0%;background:#2747A6"></div></div><span class="mono" style="font-size:14px" data-live="sampleText"></span></div>` : ""}
  </section>`;
}

function replayPanel() {
  const rp = state.replay, log = rp.log, dur = log ? replayDur(log) : 1;
  const markers = log ? log.events.filter((e) => e.m.type === "risk").reduce((acc, e) => {
    const lvl = e.m.level, prev = acc.length ? acc[acc.length - 1].lvl : "none";
    if (["amber", "red"].includes(lvl) && lvl !== prev && !(prev === "red")) acc.push({ t: e.t, lvl });
    return acc;
  }, []) : [];
  return `<section class="card" style="background-image:repeating-linear-gradient(-45deg,rgba(91,59,158,.07) 0 14px,transparent 14px 28px);border:3px dashed #5B3B9E">
    <div class="card-h"><h3 class="t">Saved session</h3><span style="font-size:14px;color:#3E2A6E;font-weight:700">Saved event timeline · not live</span></div>
    <label style="display:flex;flex-direction:column;gap:6px;font-size:15px;font-weight:700">Session log file (saved from Live or Sample mode; it stays on this device)<input type="file" id="replayFile" accept="application/json,.json" style="font-size:15px"></label>
    ${rp.error ? `<span style="font-weight:700;color:#B3261E">${esc(rp.error)}</span>` : ""}
    ${log ? `<span class="sub">${esc(rp.name)} · ${esc(log.source)} · ${esc(langByCode(log.language).name)}${log.sample ? ` · sample ${esc(log.sample)}` : ""}</span>
    <div class="row" style="gap:10px"><button data-act="play" class="btn-primary" style="background:#5B3B9E;color:#fff;min-width:150px"><span style="font-size:14px">${rp.playing ? "❚❚" : "▶"}</span>${rp.playing ? "Pause" : rp.t >= dur ? "Play again" : rp.t > 0 ? "Resume" : "Play replay"}</button>
      <button class="btn" style="color:#3E2A6E" data-act="restart">Restart</button><button class="btn mono" style="color:#3E2A6E" data-act="speed">Speed ${rp.speed}×</button>
      <span class="mono" style="font-size:16px;font-weight:700;margin-left:auto" data-live="replayTime"></span></div>
    <div aria-hidden="true" style="position:relative;height:16px;border-radius:4px;background:#E6E0F0">${markers.map((m) => `<span style="position:absolute;top:0;bottom:0;left:${((100 * m.t) / dur).toFixed(2)}%;width:5px;background:${m.lvl === "red" ? "#B3261E" : "#E0A400"};border-radius:2px"></span>`).join("")}<span data-live="replayHead" style="position:absolute;top:-3px;bottom:-3px;left:0%;width:3px;background:#17191E;border-radius:2px"></span></div>
    <label class="row" style="gap:8px;font-size:15px"><input type="checkbox" id="replaySound" ${rp.sound ? "checked" : ""} style="width:20px;height:20px;accent-color:#5B3B9E">Play the warning sounds at the recorded moments</label>` : ""}
  </section>`;
}

function actionsView(s) {
  const red = s.level === "red", amber = s.level === "amber";
  return `<section class="card"><div class="card-h"><h3 class="t">${red ? "Do this now" : "What you can do"}</h3><span class="sub">Nothing is called, sent or reported automatically</span></div>
    <p style="margin:0;font-size:17px;line-height:1.45">${red ? "Hang up. Don’t share any OTP, PIN or password, and don’t send money. Then get help if you need it." : amber ? "You can hang up at any time and call your bank on the number printed on your card." : "You can hang up at any time. Banks and police never ask for an OTP, PIN or money transfer over a call."}</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:10px">
      <a href="tel:1930" class="act" style="background:${red ? "#B3261E" : "#17191E"};color:#fff;border-color:transparent"><span class="act-t">Call 1930</span><span class="act-s">National cyber-crime helpline. Opens your phone’s dialler.</span></a>
      <button data-act="share" class="act"><span class="act-t">Tell someone you trust</span><span class="act-s">Prepares a message. You choose who gets it.</span></button>
      <a href="https://cybercrime.gov.in" target="_blank" rel="noopener noreferrer" class="act"><span class="act-t">Report online ↗</span><span class="act-s">Official portal, cybercrime.gov.in. You fill it in.</span></a>
    </div>
    ${state.share ? `<div style="padding:12px 14px;border-radius:10px;border:1.5px dashed #17191E;font-size:15px;line-height:1.45;display:flex;flex-direction:column;gap:6px"><span style="font-weight:700">${esc(state.share.status)}</span><span style="font-style:italic">${esc(state.share.text)}</span></div>` : ""}
    ${state.mode === "replay" ? `<span class="sub">These buttons are real actions — they are not part of the recording.</span>` : state.mode === "sample" ? `<span class="sub">These buttons are real actions — the sample is not a real call.</span>` : ""}
  </section>`;
}

function evalView() {
  const st = state.reportState, r = state.report;
  if (st === "loading" || st === "idle") return `<div style="padding:24px;border-radius:18px;border:1.5px dashed #17191E;font-size:18px;font-weight:700">Reading ${REPORT_URL}…</div>`;
  if (st === "error" || !r) return `<div style="padding:24px;border-radius:18px;background-color:#2A2D33;background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.07) 0 12px,transparent 12px 24px);color:#fff;display:flex;flex-direction:column;gap:10px"><h2 style="margin:0;font-size:30px;font-weight:800">No evaluation results to show</h2><p style="margin:0;font-size:18px">${esc(REPORT_URL)} — ${esc(state.reportErr)}. No results are shown rather than guessing.</p><div><button class="btn" style="background:#fff;color:#17191E;border:none" data-act="retryReport">Try again</button></div></div>`;
  const th = (l, right) => `<th style="text-align:${right ? "right" : "left"};padding:8px;border-bottom:1.5px solid #17191E;font-size:14px">${l}</th>`;
  const td = (v, right, bold) => `<td style="padding:10px 8px;border-bottom:1px solid #D6D0C2;text-align:${right ? "right" : "left"};vertical-align:top;${bold ? "font-weight:700" : ""}">${esc(v)}</td>`;
  return `<section class="card"><div class="row-between"><h2 style="margin:0;font-size:clamp(26px,3.4vw,36px);font-weight:800">How did the detector do on test calls?</h2><span class="tag" style="background:#17191E;color:#FBF9F4">DEVELOPMENT SET · NOT LIVE CALLS</span></div>
      <div class="mono row" style="gap:4px 20px;font-size:13px;color:#3B3F47"><span>Source: ${esc(REPORT_URL)}</span><span>${esc(r.dataset)}</span><span>${esc(r.provider)}</span>${r.commit ? `<span>commit ${esc(r.commit)}</span>` : ""}${r.when ? `<span>run ${esc(r.when)}</span>` : ""}${r.cost ? `<span>reported cost ${esc(r.cost)}</span>` : ""}</div>
      <div style="display:flex;flex-direction:column;gap:8px;padding:14px 16px;border-radius:12px;background:#17191E;color:#FBF9F4">${r.caveats.map((c) => `<span style="font-size:16px;line-height:1.45">${esc(c)}</span>`).join("")}</div></section>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:14px">${r.tiles.map((t) => `<div class="card" style="gap:6px;border-radius:16px;padding:18px"><span style="font-size:15px;font-weight:700">${esc(t.label)}</span><span style="font-size:40px;font-weight:800;line-height:1.05;font-variant-numeric:tabular-nums">${esc(t.frac)}</span><span style="font-size:16px;font-weight:700">${esc(t.pct)}</span><span style="font-size:14px;color:#3B3F47">${esc(t.sub)}</span>${t.flag ? `<span style="align-self:flex-start;font-size:13px;font-weight:700;padding:3px 8px;border-radius:6px;background:#B3261E;color:#fff">${esc(t.flag)}</span>` : ""}</div>`).join("")}</div>
    ${r.languages.length ? `<section class="card"><h3 class="t">By language</h3><div style="overflow-x:auto"><table class="tbl" style="min-width:560px"><thead><tr>${th("Language")}${th("Scams → red", 1)}${th("Genuine → red", 1)}${th("Red before ask", 1)}${th("Genuine → amber", 1)}</tr></thead><tbody>${r.languages.map((l) => `<tr>${td(l.lang, 0, 1)}${td(l.recall, 1)}${td(l.falseRed, 1)}${td(l.beforeAsk, 1)}${td(l.genuineAmber, 1)}</tr>`).join("")}</tbody></table></div></section>` : ""}
    <section class="card"><div class="row-between"><h3 class="t">Every call</h3>${r.latency ? `<span class="sub">${esc(r.latency.calls)} analysis calls · median ${esc(r.latency.verifier)} each · median delay after a segment ${esc(r.latency.delay)}</span>` : ""}</div>
      <div style="overflow-x:auto"><table class="tbl" style="min-width:560px"><thead><tr>${th("Call")}${th("Language")}${th("First warning", 1)}${th("First red", 1)}${th("Analysis")}${th("Failures")}</tr></thead><tbody>${r.calls.map((c) => `<tr>${td(c.id, 0, 1)}${td(c.lang)}${td(c.firstWarning, 1)}${td(c.firstRed, 1)}${td(c.status)}${td(c.failures || "none")}</tr>`).join("")}</tbody></table></div></section>
    <p class="note">${esc(Object.entries(r.definitions).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}.`).join(" "))} A sanitised export of a backend/evaluation/run_pilot.py result: numbers, status and failure categories only, no transcript text or evidence.</p>`;
}

const BANNERS = {
  live: ["#17191E", "#FBF9F4", "", "1 · LIVE MICROPHONE", "Listens to the speakerphone through this device’s microphone. It can’t hear inside the call, block the caller, or tell you for certain who is calling."],
  sample: ["#2747A6", "#FFFFFF", "", "2 · SAMPLE AUDIO — NOT A LIVE CALL", "A synthetic recording is sent through the real speech-to-text and detector. The microphone is not used."],
  replay: ["#5B3B9E", "#FFFFFF", "background-image:repeating-linear-gradient(-45deg,rgba(255,255,255,.10) 0 14px,transparent 14px 28px);", "3 · RECORDED REPLAY — NOTHING IS RUNNING", "Events saved from an earlier session are played back. The microphone, speech-to-text and detector are not running. Nothing here is happening now."],
  eval: ["#FBF9F4", "#17191E", "border:1.5px solid #17191E;", "EVALUATION REPORT", "Read from a static exported file. Results come from labelled test samples, not from live calls."],
};

const last = {};
function patch(id, html) { if (last[id] !== html) { last[id] = html; $(id).innerHTML = html; } }

// Values that change every tick, written into stable elements instead of rebuilding the cards.
function updateLive(s) {
  const rp = state.replay, dur = rp.log ? replayDur(rp.log) : 1;
  const sd = s.sampleDur || 0;
  const values = {
    clock: { text: fmt(s.audioT) },
    meter: { width: s.mic === "paused" ? 0 : Math.round(state.meter * 100) },
    sampleBar: { width: sd ? Math.min(100, Math.round((100 * s.audioT) / sd)) : 0 },
    sampleText: { text: sd ? `Sent ${fmt(Math.min(s.audioT, sd))} of ${fmt(sd)} to the pipeline${s.audioT > sd ? ` · then ${(s.audioT - sd).toFixed(1)} s of silence` : ""}` : "" },
    replayTime: { text: `${fmt(rp.t)} / ${fmt(dur)}` },
    replayHead: { left: Math.min(99.5, (100 * rp.t) / dur).toFixed(2) },
  };
  for (const el of document.querySelectorAll("[data-live]")) {
    const v = values[el.dataset.live]; if (!v) continue;
    if (v.text !== undefined && el.textContent !== v.text) el.textContent = v.text;
    if (v.width !== undefined) el.style.width = `${v.width}%`;
    if (v.left !== undefined) el.style.left = `${v.left}%`;
  }
}

function render() {
  const mode = state.mode;
  patch("tabs", [["live", "1", "Live microphone"], ["sample", "2", "Analyse sample audio"], ["replay", "3", "Recorded replay"], ["eval", "", "Evaluation report"]].map(([k, num, label]) => {
    const on = mode === k;
    return `<button data-act="mode" data-arg="${k}" aria-pressed="${on}" class="tab" style="border-color:${on ? MODE_COLOR[k] : "#17191E"};background:${on ? MODE_COLOR[k] : "transparent"};color:${on ? "#fff" : "#17191E"}">${num ? `<span class="mono tabnum">${num}</span>` : ""}<span>${label}</span></button>`;
  }).join(""));
  const [bg, ink, extra, tag, text] = BANNERS[mode];
  patch("banner", `<div class="banner" style="background-color:${bg};color:${ink};${extra}"><span class="mono btag" style="border-color:${ink}">${tag}</span><span style="font-size:16px;line-height:1.4;flex:1;min-width:240px">${text}</span></div>`);
  const cs = state.confirmSwitch;
  patch("confirm", cs ? `<div class="confirm"><span style="font-size:17px;font-weight:700;flex:1;min-width:240px">${state.s?.source === "live" ? "Live listening is on. Switching stops it and releases the microphone." : "A sample is being analysed. Switching stops it."}</span><div class="row" style="gap:8px"><button class="btn-primary" style="background:#17191E;color:#FBF9F4;min-height:48px;font-size:16px" data-act="confirmYes">${state.s?.source === "live" ? "Stop listening and switch" : "Stop and switch"}</button><button class="btn" data-act="confirmNo">Keep going</button></div></div>` : "");
  patch("settings", state.settingsOpen ? `<section class="card" style="margin-top:14px"><div class="card-h"><h3 class="t">Settings</h3><span class="sub">Saved on this device</span></div>
    <label class="row" style="gap:10px;font-size:16px"><input type="checkbox" id="autoSpeak" ${state.autoSpeak ? "checked" : ""} style="width:22px;height:22px;accent-color:#17191E">Play the spoken warning automatically on amber or red</label>
    <dl style="margin:0;display:grid;grid-template-columns:minmax(0,200px) minmax(0,1fr);gap:6px 14px;font-size:15px"><dt style="font-weight:700">Audio is sent to</dt><dd class="mono" style="margin:0">${esc(wsUrl())} (this page’s own server only)</dd><dt style="font-weight:700">Warning clips</dt><dd class="mono" style="margin:0">${CLIP_BASE}/{amber|red|test}-{hi|te|en}.mp3 or .wav</dd><dt style="font-weight:700">Evaluation report</dt><dd class="mono" style="margin:0">${REPORT_URL}</dd></dl>
    <p class="note">The app never computes a score. It shows only the level and evidence the backend sends. Nothing is saved on the server; a session log is saved only when you press “Save session log”, as a file on this device.</p></section>` : "");
  $("session").hidden = mode === "eval";
  $("eval").hidden = mode !== "eval";
  if (mode === "eval") { patch("eval", evalView()); return; }
  const s = currentSession();
  patch("picker", mode === "sample" ? samplePicker(s) : mode === "replay" ? replayPanel() : "");
  patch("warning", warningView(s));
  patch("result", sampleResult(s));
  patch("actions", actionsView(s));
  patch("healthSub", mode === "live" ? "Live pipeline status" : mode === "sample" ? "Real pipeline · sample input" : "Nothing below is running");
  patch("health", healthRows(s));
  patch("trTitle", mode === "live" ? "Transcript" : mode === "sample" ? "Sample transcript" : "Recorded transcript");
  const tr = $("tr"), near = tr.scrollHeight - tr.scrollTop - tr.clientHeight < 140;
  patch("tr", transcriptView(s));
  if (near) tr.scrollTop = tr.scrollHeight;
  updateLive(s);
  $("lang").disabled = isActive(state.s); // the transcription language is fixed for a session
  announce(s);
}

// Screen readers: the warning card is rebuilt, so announce headline changes through persistent regions,
// assertively for red.
let announced = "";
function announce(s) {
  const text = $("warning").querySelector(".headline")?.textContent || "";
  if (!text || text === announced) return;
  announced = text;
  const urgent = s.source !== "replay" && ((s.level === "red" && s.phase === "listening") || FAILS.includes(s.phase));
  $(urgent ? "alertRegion" : "statusRegion").textContent = text;
  $(urgent ? "statusRegion" : "alertRegion").textContent = "";
}

$("lang").innerHTML = LANGS.map((l) => `<option value="${l.code}">${esc(l.label)}</option>`).join("");
$("lang").value = state.lang;
if (state.mode === "eval") loadReport();
render();
window.__ck = { state, get rt() { return rt; } }; // for the browser test page and manual debugging
