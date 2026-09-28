// Browser-only lifecycle tests for capture.js against the real /ws/audio server.
// Serve with the FastAPI spike in mock-provider mode (STT_PROVIDER=mock, no Sarvam calls)
// and open lifecycle.test.html.
const $ = (id) => document.getElementById(id);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(pred, ms = 5000) {
  const t0 = Date.now();
  while (!pred()) {
    if (Date.now() - t0 > ms) throw new Error(`timeout; status="${$("status").textContent}"`);
    await wait(25);
  }
}

// Synthetic microphone, plus a record of every capture AudioContext and WebSocket capture.js creates.
const RealAC = window.AudioContext;
const RealWS = window.WebSocket;
const tracks = [];
const captureContexts = [];
const sockets = [];
navigator.mediaDevices.getUserMedia = async () => {
  const g = new RealAC();
  const osc = new OscillatorNode(g, { frequency: 440 });
  const dest = g.createMediaStreamDestination();
  osc.connect(dest);
  osc.start();
  tracks.push(dest.stream.getAudioTracks()[0]);
  return dest.stream;
};
window.AudioContext = class extends RealAC {
  constructor(...a) { super(...a); captureContexts.push(this); }
};
window.WebSocket = class extends RealWS {
  constructor(...a) { super(...a); sockets.push(this); }
};

await import("./capture.js");

const results = [];
async function test(name, fn) {
  try { await fn(); results.push(`PASS  ${name}`); }
  catch (e) { results.push(`FAIL  ${name}: ${e.message}`); }
  $("results").textContent = results.join("\n");
}
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };
const retryable = () => !$("start").disabled && $("stop").disabled;
const socketClosed = () => sockets.at(-1).readyState >= RealWS.CLOSING;
const samplesIn = (id) => parseInt($(id).textContent, 10);

function assertReleased(label) {
  assert(tracks.at(-1).readyState === "ended", `${label}: track still live`);
  assert(retryable(), `${label}: UI not retryable`);
}

async function startListening() {
  $("start").click();
  await until(() => $("status").textContent.startsWith("Listening"));
  await until(() => samplesIn("server") > 0);
}
async function stopAndWait(expected = "Stopped") {
  $("stop").click();
  await until(() => $("status").textContent === expected);
}

await test("Start → Stop → Start → Stop streams to the server and releases the mic", async () => {
  for (let round = 1; round <= 2; round++) {
    await startListening();
    assert(tracks.at(-1).readyState === "live", `round ${round}: track not live while listening`);
    await wait(400);
    await stopAndWait();
    assertReleased(`round ${round}`);
    assert(captureContexts.at(-1).state === "closed", `round ${round}: context not closed`);
    await until(socketClosed);
    const sent = samplesIn("sent");
    assert(sent > 0, `round ${round}: nothing sent`);
    assert(samplesIn("server") === sent, `round ${round}: server ${samplesIn("server")} != sent ${sent}`);
    assert($("sent").textContent.endsWith("0 dropped"), `round ${round}: frames dropped on localhost`);
  }
});

await test("forced source.connect failure releases mic, context and socket", async () => {
  const realConnect = AudioNode.prototype.connect;
  AudioNode.prototype.connect = function (...a) {
    if (this instanceof MediaStreamAudioSourceNode) throw new DOMException("forced", "InvalidAccessError");
    return realConnect.apply(this, a);
  };
  try {
    $("start").click();
    await until(() => $("status").textContent.startsWith("Could not start"));
  } finally {
    AudioNode.prototype.connect = realConnect;
  }
  assert($("status").textContent.includes("InvalidAccessError"), "error name not shown");
  assertReleased("connect failure");
  assert(captureContexts.at(-1).state === "closed", "context not closed");
  await until(socketClosed);
  await startListening();
  await stopAndWait();
});

await test("Stop restores a retryable UI when ctx.close() rejects", async () => {
  await startListening();
  const realClose = RealAC.prototype.close;
  RealAC.prototype.close = () => Promise.reject(new DOMException("forced", "InvalidStateError"));
  try {
    await stopAndWait("Stopped (audio context did not close cleanly)");
  } finally {
    RealAC.prototype.close = realClose;
  }
  assertReleased("close rejected");
  await until(socketClosed);
});

await test("a server error mid-session releases the mic and allows retry", async () => {
  await startListening();
  const realSend = RealWS.prototype.send;
  RealWS.prototype.send = function (data) {
    RealWS.prototype.send = realSend;
    return realSend.call(this, data instanceof ArrayBuffer ? new Uint8Array(3) : data); // misaligned frame
  };
  await until(() => $("status").textContent.startsWith("Server error"));
  RealWS.prototype.send = realSend;
  assert($("status").textContent.includes("16-bit"), `unexpected message: ${$("status").textContent}`);
  assertReleased("server error");
  assert(captureContexts.at(-1).state === "closed", "context not closed");
  await startListening();
  await stopAndWait();
});

await test("an unreachable server releases the mic", async () => {
  const original = location.href;
  history.replaceState(null, "", "?ws=ws://127.0.0.1:9/ws/audio");
  try {
    $("start").click();
    await until(() => $("status").textContent.startsWith("Could not start"));
  } finally {
    history.replaceState(null, "", original);
  }
  assert($("status").textContent.includes("could not reach"), `unexpected message: ${$("status").textContent}`);
  assertReleased("unreachable server");
});

await test("socket closing after ready but before audio setup completes never shows Listening", async () => {
  const statuses = [];
  const observer = new MutationObserver(() => statuses.push($("status").textContent));
  observer.observe($("status"), { childList: true, characterData: true, subtree: true });
  const realAddModule = AudioWorklet.prototype.addModule;
  AudioWorklet.prototype.addModule = async function (...a) {
    const ws = sockets.at(-1);
    ws.close(); // the socket is past ready: capture.js only builds audio after the server's reply
    await new Promise((r) => ws.addEventListener("close", r, { once: true }));
    return realAddModule.apply(this, a);
  };
  try {
    $("start").click();
    await until(() => $("status").textContent.startsWith("Could not start"));
  } finally {
    AudioWorklet.prototype.addModule = realAddModule;
    observer.disconnect();
  }
  await wait(300);
  assert(!statuses.some((t) => t.startsWith("Listening")), `showed Listening: ${statuses.join(" | ")}`);
  assert($("status").textContent.includes("during setup"), `unexpected message: ${$("status").textContent}`);
  assertReleased("close during setup");
  assert(captureContexts.at(-1).state === "closed", "context not closed");
  await startListening();
  await stopAndWait();
});

// Replaces the next text message capture.js sends (the stop request) for one call.
function interceptStopMessage(replace) {
  const realSend = RealWS.prototype.send;
  RealWS.prototype.send = function (data) {
    if (typeof data !== "string") return realSend.call(this, data);
    RealWS.prototype.send = realSend;
    return replace(this, (d) => realSend.call(this, d));
  };
  return () => { RealWS.prototype.send = realSend; };
}

async function stopExpectingIncomplete(label, replace, reason) {
  await startListening();
  const restore = interceptStopMessage(replace);
  try {
    $("stop").click();
    await until(() => $("status").textContent.startsWith("Stopped"), 12000);
  } finally {
    restore();
  }
  const status = $("status").textContent;
  assert(status.startsWith("Stopped, session incomplete") && status.includes(reason), `${label}: "${status}"`);
  assertReleased(label);
  await until(socketClosed);
}

await test("Stop without the server's stopped reply reports a timeout", async () => {
  await stopExpectingIncomplete("timeout", () => {}, "did not confirm within 8 s");
});

await test("Stop answered by a server error reports the error", async () => {
  await stopExpectingIncomplete("server error", (_ws, send) => send("not a stop"), "server error:");
});

await test("Stop interrupted by the connection closing reports an early close", async () => {
  await stopExpectingIncomplete("early close", (ws) => ws.close(4000, "test"), "closed (code 4000)");
});

await test("a normal Stop reports success only after the server's reply", async () => {
  await startListening();
  $("stop").click();
  await until(() => $("status").textContent.startsWith("Stopped"));
  assert($("status").textContent === "Stopped", `"${$("status").textContent}"`);
  assert(samplesIn("server") === samplesIn("sent"), "server total does not match sent");
});

const lines = () => [...$("transcript").children].map((li) => li.textContent);

await test("final transcript segments appear once and Stop waits for the flushed segment", async () => {
  await startListening();
  await until(() => lines().includes("mock segment 1"), 4000); // mock emits one segment per second of audio
  $("stop").click();
  await until(() => $("status").textContent.startsWith("Stopped"));
  assert($("status").textContent === "Stopped", `"${$("status").textContent}"`);
  const got = lines();
  assert(new Set(got).size === got.length, `duplicate segments: ${got.join(" | ")}`);
  assert(got.length >= 2, `flushed segment missing: ${got.join(" | ")}`);
  assert($("provisional").textContent === "", "provisional text left after Stop");
});

await test("audio dropped by the browser is shown as a gap and makes the session incomplete", async () => {
  await startListening();
  const desc = Object.getOwnPropertyDescriptor(RealWS.prototype, "bufferedAmount");
  Object.defineProperty(RealWS.prototype, "bufferedAmount", { configurable: true, get: () => 1e9 });
  try {
    await until(() => lines().some((t) => t.startsWith("[gap:") && t.includes("not sent")));
  } finally {
    Object.defineProperty(RealWS.prototype, "bufferedAmount", desc);
  }
  await until(() => !$("sent").textContent.endsWith(" 0 dropped"));
  $("stop").click();
  await until(() => $("status").textContent.startsWith("Stopped"));
  const status = $("status").textContent;
  assert(status.startsWith("Stopped, session incomplete") && status.includes("not sent"), `"${status}"`);
  assert(lines().filter((t) => t.startsWith("[gap:")).length === 1, `gaps not coalesced: ${lines().join(" | ")}`);
  assertReleased("client gap");
});

results.push(results.every((r) => r.startsWith("PASS")) ? "\nALL PASSED" : "\nFAILURES");
$("results").textContent = results.join("\n");
document.title = results.at(-1).trim();
