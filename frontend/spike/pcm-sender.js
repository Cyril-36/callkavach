// Batches 16 kHz Int16 samples into fixed frames and sends them as little-endian bytes.
// If the socket's send queue exceeds maxBufferedBytes, frames are dropped and counted
// instead of queued, so a slow connection can never buffer audio without bound.

export function toLittleEndianBytes(int16) {
  const buf = new ArrayBuffer(int16.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < int16.length; i++) view.setInt16(i * 2, int16[i], true);
  return buf;
}

export class PcmSender {
  constructor(socket, { frameSamples = 1600, maxBufferedBytes = 64000 } = {}) {
    this.socket = socket;
    this.maxBufferedBytes = maxBufferedBytes;
    this.pending = new Int16Array(frameSamples);
    this.pendingLen = 0;
    this.sentSamples = 0;
    this.droppedSamples = 0;
  }

  push(samples) {
    let i = 0;
    while (i < samples.length) {
      const n = Math.min(samples.length - i, this.pending.length - this.pendingLen);
      this.pending.set(samples.subarray(i, i + n), this.pendingLen);
      this.pendingLen += n;
      i += n;
      if (this.pendingLen === this.pending.length) this.flush();
    }
  }

  // Sends whatever is pending, including a partial frame.
  flush() {
    if (this.pendingLen === 0) return;
    const frame = this.pending.slice(0, this.pendingLen);
    this.pendingLen = 0;
    if (this.socket.readyState !== 1 || this.socket.bufferedAmount + frame.length * 2 > this.maxBufferedBytes) {
      this.droppedSamples += frame.length;
      return;
    }
    this.socket.send(toLittleEndianBytes(frame));
    this.sentSamples += frame.length;
  }
}
