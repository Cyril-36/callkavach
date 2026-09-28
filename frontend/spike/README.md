# Microphone capture spike

Browser microphone → AudioWorklet (mono Float32) → streaming resampler (Blackman-windowed sinc low-pass, then linear interpolation) → 16 kHz Int16. Audio stays in memory and is discarded; nothing is stored or sent.

```bash
node --test frontend/spike/resample.test.js
```

To try the page, serve this folder over localhost (microphone access needs a secure context) and open it:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 -d frontend/spike
```
