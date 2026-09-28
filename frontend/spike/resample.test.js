import { test } from "node:test";
import assert from "node:assert/strict";
import { Resampler, toInt16 } from "./resample.js";

const tone = (hz, rate, secs) => Float32Array.from({ length: rate * secs }, (_, i) => Math.sin((2 * Math.PI * hz * i) / rate));
const rms = (a, from = 0) => Math.sqrt(a.slice(from).reduce((s, v) => s + v * v, 0) / (a.length - from));

function inChunks(r, x, size = 128) {
  const parts = [];
  for (let i = 0; i < x.length; i += size) parts.push(...r.process(x.subarray(i, i + size)));
  return Float32Array.from(parts);
}

// Dominant frequency via correlation with a probe tone (skip the filter warm-up).
function amplitudeAt(y, hz, rate, from = 200) {
  let re = 0, im = 0;
  for (let i = from; i < y.length; i++) {
    re += y[i] * Math.cos((2 * Math.PI * hz * i) / rate);
    im += y[i] * Math.sin((2 * Math.PI * hz * i) / rate);
  }
  return (2 * Math.hypot(re, im)) / (y.length - from);
}

for (const inRate of [48000, 44100]) {
  test(`${inRate} Hz -> 16 kHz: one second gives ~16000 samples`, () => {
    const y = inChunks(new Resampler(inRate), tone(1000, inRate, 1));
    assert.ok(Math.abs(y.length - 16000) <= 1, `got ${y.length}`);
  });

  test(`${inRate} Hz -> 16 kHz: a 1 kHz tone stays a 1 kHz tone`, () => {
    const y = inChunks(new Resampler(inRate), tone(1000, inRate, 1));
    assert.ok(amplitudeAt(y, 1000, 16000) > 0.95, "1 kHz amplitude preserved");
    assert.ok(amplitudeAt(y, 1000 * (inRate / 16000), 16000) < 0.02, "not merely relabelled");
  });

  test(`${inRate} Hz -> 16 kHz: a 12 kHz tone is filtered, not aliased`, () => {
    const y = inChunks(new Resampler(inRate), tone(12000, inRate, 1));
    assert.ok(rms(y, 200) < 0.02, `aliased energy rms ${rms(y, 200)}`);
  });

  test(`${inRate} Hz: 128-frame chunks match a single pass`, () => {
    const x = tone(440, inRate, 1);
    const whole = new Resampler(inRate).process(x);
    const chunked = inChunks(new Resampler(inRate), x);
    assert.ok(Math.abs(whole.length - chunked.length) <= 1);
    const n = Math.min(whole.length, chunked.length);
    for (let i = 0; i < n; i++) assert.ok(Math.abs(whole[i] - chunked[i]) < 1e-5, `sample ${i}`);
  });
}

test("16 kHz input passes through unchanged", () => {
  const x = tone(1000, 16000, 1);
  const y = inChunks(new Resampler(16000), x);
  assert.ok(Math.abs(y.length - x.length) <= 1);
  for (let i = 0; i < y.length; i++) assert.ok(Math.abs(y[i] - x[i]) < 1e-6);
});

test("toInt16 clamps and scales", () => {
  assert.deepEqual(Array.from(toInt16(Float32Array.of(0, 1, -1, 2, -2, 0.5))), [0, 32767, -32768, 32767, -32768, 16383]);
});
