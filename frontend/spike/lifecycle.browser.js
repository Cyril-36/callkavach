// Browser-only lifecycle tests for capture.js against the real /ws/audio server.
// Serve with the FastAPI spike (backend/spike/audio_ws.py) and open lifecycle.test.html.
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

results.push(results.every((r) => r.startsWith("PASS")) ? "\nALL PASSED" : "\nFAILURES");
$("results").textContent = results.join("\n");
document.title = results.at(-1).trim();
