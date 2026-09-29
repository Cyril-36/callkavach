#!/usr/bin/env bash
# Generate synthetic code-mixed test audio with macOS voices (no real call material).
# Output: 16 kHz, mono, 16-bit PCM WAV in backend/spike/samples/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p samples

make() {  # name voice text
  say -v "$2" -o "samples/$1.aiff" "$3"
  ffmpeg -loglevel error -y -i "samples/$1.aiff" -ar 16000 -ac 1 -sample_fmt s16 "samples/$1.wav"
  rm "samples/$1.aiff"
  echo "samples/$1.wav"
}

# Telugu-English: slide 3 digital-arrest lines, synthetic.
make te_en_digital_arrest Geeta "నేను Mumbai Cyber Crime నుండి Inspector Sharma మాట్లాడుతున్నాను. మీ పేరు మీద ఒక parcel లో drugs మరియు fake passports దొరికాయి. ఎవరికీ చెప్పకండి, call లోనే ఉండండి."
# Hindi-English: KYC / bank pattern, synthetic.
make hi_en_kyc Lekha "मैं State Bank के KYC department से बोल रहा हूँ। आपका account आज block हो जाएगा। अभी जो OTP आया है वो बताइए।"
