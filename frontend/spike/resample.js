// Streaming resampler: anti-aliasing low-pass (windowed sinc) then linear interpolation.
// State carries across chunks, so feeding 128-frame worklet blocks gives the same
// output as resampling the whole signal at once.

function lowpass(cutoff, taps) {
  // cutoff in cycles per input sample (0..0.5); Blackman-windowed sinc, unity DC gain.
  const k = new Float32Array(taps);
  const mid = (taps - 1) / 2;
  let sum = 0;
  for (let n = 0; n < taps; n++) {
    const x = n - mid;
    const sinc = x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
    const w = 0.42 - 0.5 * Math.cos((2 * Math.PI * n) / (taps - 1)) + 0.08 * Math.cos((4 * Math.PI * n) / (taps - 1));
    k[n] = sinc * w;
    sum += k[n];
  }
  for (let n = 0; n < taps; n++) k[n] /= sum;
  return k;
}

export class Resampler {
  constructor(inRate, outRate = 16000, taps = 63) {
    this.step = inRate / outRate;
    // Cut off at 90% of the output Nyquist so content above 8 kHz cannot alias down.
    this.kernel = inRate > outRate ? lowpass((0.45 * outRate) / inRate, taps) : Float32Array.of(1);
    this.hist = new Float32Array(this.kernel.length - 1);
    this.prev = 0; // last filtered sample of the previous chunk
    this.t = 0; // next output position, relative to the current chunk's first filtered sample
  }

  process(input) {
    const K = this.kernel;
    const L = K.length;
    const n = input.length;
    if (n === 0) return new Float32Array(0);

    const x = new Float32Array(L - 1 + n);
    x.set(this.hist);
    x.set(input, L - 1);
    const y = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      let acc = 0;
      for (let j = 0; j < L; j++) acc += K[j] * x[i + L - 1 - j];
      y[i] = acc;
    }
    this.hist = x.slice(x.length - (L - 1));

    const out = [];
    while (this.t < n - 1) {
      const i = Math.floor(this.t);
      const f = this.t - i;
      const a = i < 0 ? this.prev : y[i];
      out.push(a + (y[i + 1] - a) * f);
      this.t += this.step;
    }
    this.t -= n;
    this.prev = y[n - 1];
    return Float32Array.from(out);
  }
}

export function toInt16(samples) {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}
