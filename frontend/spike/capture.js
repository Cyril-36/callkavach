import { Resampler, toInt16 } from "./resample.js";

const $ = (id) => document.getElementById(id);
let session = null;

function show(fields) {
  for (const [id, value] of Object.entries(fields)) $(id).textContent = value;
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

  // Let the browser pick its native rate; we resample ourselves.
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule("./pcm-worklet.js");
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "pcm-capture");
  const resampler = new Resampler(ctx.sampleRate, 16000);
  session = { stream, ctx, source, node, inSamples: 0, outSamples: 0 };

  node.port.onmessage = ({ data }) => {
    const pcm16 = toInt16(resampler.process(data)); // 16 kHz Int16 mono; kept only in memory, discarded
    session.inSamples += data.length;
    session.outSamples += pcm16.length;
    show({
      duration: `${(session.inSamples / ctx.sampleRate).toFixed(2)} s`,
      outCount: `${session.outSamples} (${(session.outSamples / 16000).toFixed(2)} s at 16 kHz)`,
    });
  };
  source.connect(node);

  const trackRate = stream.getAudioTracks()[0].getSettings().sampleRate;
  show({
    status: "Listening (audio is not stored or sent anywhere)",
    rate: `${ctx.sampleRate} Hz (AudioContext)${trackRate ? `, track reports ${trackRate} Hz` : ""}`,
    duration: "0.00 s",
    outCount: "0",
  });
  $("stop").disabled = false;
}

async function stop() {
  if (!session) return;
  $("stop").disabled = true;
  const { stream, ctx, source, node } = session;
  node.port.onmessage = null;
  source.disconnect();
  node.disconnect();
  stream.getTracks().forEach((t) => t.stop());
  await ctx.close();
  session = null;
  show({ status: "Stopped" });
  $("start").disabled = false;
}

$("start").onclick = start;
$("stop").onclick = stop;
