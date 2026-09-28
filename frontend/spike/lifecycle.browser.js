// Browser-only lifecycle tests for capture.js. Open lifecycle.test.html over localhost.
const $ = (id) => document.getElementById(id);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(pred, ms = 5000) {
  const t0 = Date.now();
  while (!pred()) {
    if (Date.now() - t0 > ms) throw new Error(`timeout; status="${$("status").textContent}"`);
    await wait(25);
  }
}

// Synthetic microphone and a record of every capture AudioContext created by capture.js.
const RealAC = window.AudioContext;
const tracks = [];
const captureContexts = [];
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

await import("./capture.js");

const results = [];
async function test(name, fn) {
  try { await fn(); results.push(`PASS  ${name}`); }
  catch (e) { results.push(`FAIL  ${name}: ${e.message}`); }
  $("results").textContent = results.join("\n");
}
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };
const retryable = () => !$("start").disabled && $("stop").disabled;

async function startListening() {
  $("start").click();
  await until(() => $("status").textContent.startsWith("Listening"));
  await until(() => parseInt($("outCount").textContent, 10) > 0);
}
async function stopAndWait(expected = "Stopped") {
  $("stop").click();
  await until(() => $("status").textContent === expected);
}

await test("Start → Stop → Start → Stop releases the mic each time", async () => {
  for (let round = 1; round <= 2; round++) {
    await startListening();
    assert(tracks.at(-1).readyState === "live", `round ${round}: track not live while listening`);
    assert($("start").disabled && !$("stop").disabled, `round ${round}: buttons wrong while listening`);
    await stopAndWait();
    assert(tracks.at(-1).readyState === "ended", `round ${round}: track still live after Stop`);
    assert(captureContexts.at(-1).state === "closed", `round ${round}: context not closed`);
    assert(retryable(), `round ${round}: UI not retryable after Stop`);
    const frozen = $("outCount").textContent;
    await wait(300);
    assert($("outCount").textContent === frozen, `round ${round}: counter kept updating after Stop`);
  }
});

await test("forced source.connect failure releases everything and allows retry", async () => {
  const realConnect = AudioNode.prototype.connect;
  AudioNode.prototype.connect = function (...a) {
    if (this instanceof MediaStreamAudioSourceNode) throw new DOMException("forced", "InvalidAccessError");
    return realConnect.apply(this, a);
  };
  try {
    $("start").click();
    await until(() => $("status").textContent.startsWith("Audio setup failed"));
  } finally {
    AudioNode.prototype.connect = realConnect;
  }
  assert($("status").textContent.includes("InvalidAccessError"), "error name not shown");
  assert(tracks.at(-1).readyState === "ended", "track still live after failure");
  assert(captureContexts.at(-1).state === "closed", "context not closed after failure");
  assert(retryable(), "UI not retryable after failure");
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
  assert(tracks.at(-1).readyState === "ended", "track still live when close rejected");
  assert(retryable(), "UI not retryable when close rejected");
  await startListening();
  await stopAndWait();
});

results.push(results.every((r) => r.startsWith("PASS")) ? "\nALL PASSED" : "\nFAILURES");
$("results").textContent = results.join("\n");
document.title = results.at(-1).trim();
