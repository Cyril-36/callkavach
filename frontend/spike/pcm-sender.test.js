import { test } from "node:test";
import assert from "node:assert/strict";
import { PcmSender, toLittleEndianBytes } from "./pcm-sender.js";

function fakeSocket({ readyState = 1, bufferedAmount = 0 } = {}) {
  return { readyState, bufferedAmount, sent: [], send(buf) { this.sent.push(new Uint8Array(buf)); } };
}

test("bytes are signed 16-bit little-endian", () => {
  const bytes = new Uint8Array(toLittleEndianBytes(Int16Array.of(1, -2, 0x1234, -32768, 32767)));
  assert.deepEqual(Array.from(bytes), [0x01, 0x00, 0xfe, 0xff, 0x34, 0x12, 0x00, 0x80, 0xff, 0x7f]);
});

test("small worklet blocks are batched into whole frames", () => {
  const ws = fakeSocket();
  const s = new PcmSender(ws, { frameSamples: 1600 });
  for (let i = 0; i < 100; i++) s.push(new Int16Array(43)); // 4300 samples, ~worklet block size at 48 kHz
  assert.equal(ws.sent.length, 2);
  assert.ok(ws.sent.every((f) => f.length === 3200));
  assert.equal(s.sentSamples, 3200);
  assert.equal(s.pendingLen, 1100);
  s.flush();
  assert.equal(ws.sent.at(-1).length, 2200);
  assert.equal(s.sentSamples, 4300);
  s.flush(); // nothing pending: no empty frame
  assert.equal(ws.sent.length, 3);
});

test("a block larger than a frame is split, preserving sample order", () => {
  const ws = fakeSocket();
  const s = new PcmSender(ws, { frameSamples: 4 });
  s.push(Int16Array.of(1, 2, 3, 4, 5, 6, 7, 8, 9, 10));
  s.flush();
  const values = ws.sent.flatMap((f) => Array.from(new Int16Array(f.buffer)));
  assert.deepEqual(values, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.deepEqual(ws.sent.map((f) => f.length / 2), [4, 4, 2]);
});

test("frames are dropped, not queued, when the socket buffer is full", () => {
  const ws = fakeSocket({ bufferedAmount: 64000 });
  const s = new PcmSender(ws, { frameSamples: 1600, maxBufferedBytes: 64000 });
  s.push(new Int16Array(3200));
  assert.equal(ws.sent.length, 0);
  assert.equal(s.droppedSamples, 3200);
  ws.bufferedAmount = 0; // socket drained: sending resumes
  s.push(new Int16Array(1600));
  assert.equal(ws.sent.length, 1);
  assert.equal(s.sentSamples, 1600);
});

test("nothing is sent on a socket that is not open", () => {
  const ws = fakeSocket({ readyState: 3 });
  const s = new PcmSender(ws, { frameSamples: 10 });
  s.push(new Int16Array(25));
  s.flush();
  assert.equal(ws.sent.length, 0);
  assert.equal(s.droppedSamples, 25);
});
