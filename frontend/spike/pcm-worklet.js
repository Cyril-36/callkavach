// Forwards each 128-frame block to the main thread as mono Float32 (channels averaged).
class PcmCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (channels.length > 0) {
      const mono = new Float32Array(channels[0].length);
      for (const ch of channels) for (let i = 0; i < mono.length; i++) mono[i] += ch[i] / channels.length;
      this.port.postMessage(mono, [mono.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
