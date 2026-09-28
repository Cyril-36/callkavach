import { Resampler, toInt16 } from "./resample.js";
import { PcmSender } from "./pcm-sender.js";

const READY_TIMEOUT_MS = 5000;
const STOP_TIMEOUT_MS = 2000;
const $ = (id) => document.getElementById(id);
let session = null;

function show(fields) {
  for (const [id, value] of Object.entries(fields)) $(id).textContent = value;
}

function wsUrl() {
  const override = new URLSearchParams(location.search).get("ws");
  return override || `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/audio`;
}

function parse(data) {
  try { return typeof data === "string" ? JSON.parse(data) : null; } catch { return null; }
}

const serverTotals = (m) => `${m.samples} samples (${m.duration_s.toFixed(2)} s)`;

// Opens the socket, declares the audio format and resolves once the server says ready.
function connect(s) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl());
    ws.binaryType = "arraybuffer";
    s.ws = ws;
    const timer = setTimeout(() => reject(new Error("audio server did not answer in time.")), READY_TIMEOUT_MS);
    ws.onopen = () => ws.send(JSON.stringify({ type: "start", encoding: "pcm_s16le", channels: 1, sample_rate: 16000 }));
    ws.onmessage = ({ data }) => {
      clearTimeout(timer);
      const msg = parse(data);
      if (msg?.type === "ready") resolve();
      else reject(new Error(`server refused: ${msg?.message || "unexpected reply"}`));
    };
    ws.onclose = (e) => {
      clearTimeout(timer);
      reject(new Error(`could not reach the audio server (code ${e.code}).`));
    };
  });
}

function closeSocket(s) {
  const ws = s.ws;
  if (!ws) return;
  ws.onopen = ws.onmessage = ws.onclose = null;
  if (ws.readyState < 2) ws.close(1000);
}

// Best-effort teardown: every step runs even if an earlier one throws.
async function release(s, { keepSocket = false } = {}) {
  if (s.node) s.node.port.onmessage = null;
  const steps = [
    () => s.source?.disconnect(),
    () => s.node?.disconnect(),
    () => s.stream.getTracks().forEach((t) => t.stop()),
    () => keepSocket || closeSocket(s),
  ];
  for (const step of steps) {
    try { step(); } catch {}
  }
  if (s.ctx && s.ctx.state !== "closed") {
    try { await s.ctx.close(); } catch { return false; }
  }
  return true;
}

// Server error or dropped connection while listening: release everything, allow retry.
async function fail(s, message) {
  if (s.done || s.stopping) return;
  s.done = true;
  if (session === s) session = null;
  $("stop").disabled = true;
  await release(s);
  show({ status: message });
  $("start").disabled = false;
}

async function start() {
  $("start").disabled = true;
  show({ status: "Requesting microphone…" });
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
  } catch (e) {
    const reason =
      e.name === "NotAllowedError" ? "Microphone permission denied. Allow it in the browser and try again."
      : e.name === "NotFoundError" ? "No microphone found."
      : `Microphone unavailable: ${e.name}`;
    show({ status: reason });
    $("start").disabled = false;
    return;
  }

  const s = { stream, done: false, stopping: false, inSamples: 0, outSamples: 0 };
  try {
    show({ status: "Connecting to audio server…" });
    await connect(s);

    // From here the socket can fail at any time. Before the session is live, record the
    // failure so setup aborts; once live, tear down; while stopping, report the outcome.
    const socketFailed = (message) => {
      if (s.stopping) s.onStopped?.({ ok: false, why: message });
      else if (session === s) fail(s, `${message[0].toUpperCase()}${message.slice(1)}. Microphone released.`);
      else s.setupError ??= message;
    };
    s.ws.onmessage = ({ data }) => {
      if (s.done) return;
      const msg = parse(data);
      if (msg?.type === "ack") show({ server: serverTotals(msg) });
      else if (msg?.type === "stopped") { show({ server: serverTotals(msg) }); s.onStopped?.({ ok: true }); }
      else if (msg?.type === "error") socketFailed(`server error: ${msg.message}`);
    };
    s.ws.onclose = (e) => {
      if (!s.done) socketFailed(`connection to audio server closed (code ${e.code})`);
    };

    // Let the browser pick its native rate; we resample ourselves.
    s.ctx = new AudioContext();
    await s.ctx.audioWorklet.addModule("./pcm-worklet.js");
    s.source = s.ctx.createMediaStreamSource(stream);
    s.node = new AudioWorkletNode(s.ctx, "pcm-capture");
    const resampler = new Resampler(s.ctx.sampleRate, 16000);
    s.sender = new PcmSender(s.ws);

    s.node.port.onmessage = ({ data }) => {
      if (s.done || s.stopping) return; // late message from a stopped or failed session
      const pcm16 = toInt16(resampler.process(data)); // 16 kHz Int16 mono; not stored
      s.inSamples += data.length;
      s.outSamples += pcm16.length;
      s.sender.push(pcm16);
      show({
        duration: `${(s.inSamples / s.ctx.sampleRate).toFixed(2)} s`,
        outCount: `${s.outSamples} (${(s.outSamples / 16000).toFixed(2)} s at 16 kHz)`,
        sent: `${s.sender.sentSamples} sent, ${s.sender.droppedSamples} dropped`,
      });
    };
    s.source.connect(s.node);

    // No await between this check and going live, so the socket cannot fail unnoticed.
    if (s.setupError || s.ws.readyState !== WebSocket.OPEN) {
      throw new Error(`${s.setupError || "connection to audio server closed"} during setup.`);
    }
    const trackRate = stream.getAudioTracks()[0].getSettings().sampleRate;
    session = s;
    show({
      status: "Listening (audio is streamed to the local server, not stored)",
      rate: `${s.ctx.sampleRate} Hz (AudioContext)${trackRate ? `, track reports ${trackRate} Hz` : ""}`,
      duration: "0.00 s",
      outCount: "0",
      sent: "0 sent, 0 dropped",
      server: "0 samples (0.00 s)",
    });
    $("stop").disabled = false;
  } catch (e) {
    s.done = true;
    await release(s);
    show({ status: `Could not start: ${e instanceof DOMException ? e.name : e.message} Try again.` });
    $("start").disabled = false;
  }
}

async function stop() {
  const s = session;
  if (!s) return;
  session = null;
  s.stopping = true;
  $("stop").disabled = true;
  if (s.node) s.node.port.onmessage = null;
  s.sender.flush();
  const socketOpen = s.ws.readyState === WebSocket.OPEN;
  // First outcome wins: the server's stopped reply, a server error, an early close, or the timeout.
  const outcome = new Promise((resolve) => {
    s.onStopped = resolve;
    if (!socketOpen) resolve({ ok: false, why: "connection to audio server was already closed" });
    setTimeout(() => resolve({ ok: false, why: `server did not confirm within ${STOP_TIMEOUT_MS / 1000} s` }), STOP_TIMEOUT_MS);
  });
  if (socketOpen) s.ws.send(JSON.stringify({ type: "stop" }));
  const clean = await release(s, { keepSocket: true }); // the microphone is released before waiting on the server
  const { ok, why } = await outcome;
  s.done = true;
  closeSocket(s);
  const status = ok
    ? (clean ? "Stopped" : "Stopped (audio context did not close cleanly)")
    : `Stopped, session incomplete: ${why}.${clean ? "" : " Audio context did not close cleanly."}`;
  show({ status, sent: `${s.sender.sentSamples} sent, ${s.sender.droppedSamples} dropped` });
  $("start").disabled = false;
}

$("start").onclick = start;
$("stop").onclick = stop;
