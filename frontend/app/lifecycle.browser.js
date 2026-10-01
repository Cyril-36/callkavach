// Browser lifecycle tests for the listener app. Run the relay with STT_PROVIDER=mock LLM_PROVIDER=off
// (no paid calls) and open /lifecycle.test.html. The app runs unchanged in a same-origin iframe; the
// microphone is a synthetic oscillator and AudioWorklet loading can be delayed or failed on purpose.
const results = document.getElementById("results");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadApp() {
  return new Promise((resolve) => {
    document.getElementById("frame")?.remove();
    const f = document.createElement("iframe");
    f.id = "frame";
    f.src = "/#live";
    f.style.cssText = "width:420px;height:600px;border:1px solid #999";
    f.onload = async () => {
      const w = f.contentWindow;
      while (!w.__ck) await sleep(20);
      w.navigator.mediaDevices.getUserMedia = async () => {
        const c = new w.AudioContext(), o = c.createOscillator(), d = c.createMediaStreamDestination();
        o.connect(d); o.start();
        return d.stream;
      };
      resolve(w);
    };
    document.body.append(f);
  });
}

// Delays (and optionally rejects) AudioWorklet.addModule, the step between `ready` and capture.
function slowWorklet(w, ms, { reject = false } = {}) {
  const original = w.AudioWorklet.prototype.addModule;
  w.AudioWorklet.prototype.addModule = async function (...args) {
    await sleep(ms);
    if (reject) throw new w.DOMException("forced worklet failure", "AbortError");
    return original.apply(this, args);
  };
}

const click = (w, act) => w.document.querySelector(`[data-act="${act}"]`).click();
async function until(w, pred, ms, what) {
  const end = performance.now() + ms;
  while (performance.now() < end) { if (pred(w.__ck.state.s)) return; await sleep(50); }
  throw new Error(`timed out waiting for ${what}; phase=${w.__ck.state.s?.phase}`);
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

async function stopConfirmed(w) {
  await until(w, (s) => s.phase === "stopped" || s.phase === "micerror", 20000, "stopped");
  const s = w.__ck.state.s;
  assert(s.phase === "stopped", `ended in ${s.phase}: ${s.error}`);
  assert(s.stopInfo.confirmed, `the server's stopped reply never arrived: ${JSON.stringify(s.stopInfo.problems)}`);
  assert(s.mic === "released", `mic is ${s.mic}`);
  assert(!w.__ck.rt, "session runtime still held");
  await sleep(2000); // a late worklet setup must not reopen capture or turn the result into an error
  assert(w.__ck.state.s.phase === "stopped", `phase changed after Stop to ${w.__ck.state.s.phase}`);
}

const tests = {
  "Stop right after ready, while the audio worklet is still loading, still reaches the server": async () => {
    const w = await loadApp();
    slowWorklet(w, 2500);
    click(w, "start");
    await until(w, (s) => s.phase === "listening", 10000, "listening");
    click(w, "stop");
    await stopConfirmed(w);
  },
  "Stop during setup, then the worklet fails: Stop still completes and no mic error is shown": async () => {
    const w = await loadApp();
    slowWorklet(w, 1500, { reject: true });
    click(w, "start");
    await until(w, (s) => s.phase === "listening", 10000, "listening");
    click(w, "stop");
    await stopConfirmed(w);
  },
  "a worklet failure while listening (no Stop) is reported and releases the mic": async () => {
    const w = await loadApp();
    slowWorklet(w, 200, { reject: true });
    click(w, "start");
    await until(w, (s) => s.phase === "micerror", 10000, "micerror");
    assert(!w.__ck.rt, "session runtime still held");
  },
  "Start → Stop → Start streams audio, and each Stop is confirmed by the server": async () => {
    const w = await loadApp();
    for (let i = 0; i < 2; i++) {
      click(w, "start");
      await until(w, (s) => s.phase === "listening" && s.segs.length === 0, 10000, "a fresh listening session");
      await until(w, (s) => s.segs.length >= 1, 10000, "a transcript");
      click(w, "stop");
      await stopConfirmed(w);
    }
  },
};

document.getElementById("run").addEventListener("click", async () => {
  document.getElementById("run").disabled = true;
  let failed = 0;
  for (const [name, fn] of Object.entries(tests)) {
    const li = document.createElement("li");
    try { await fn(); li.textContent = `PASS  ${name}`; }
    catch (e) { failed++; li.textContent = `FAIL  ${name}: ${e.message}`; }
    results.append(li);
  }
  document.getElementById("frame")?.remove();
  document.title = failed ? `${failed} FAILED` : "ALL PASSED";
});
