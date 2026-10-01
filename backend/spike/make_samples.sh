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
# Hindi-English genuine look-alikes, synthetic: a negated OTP warning, and a delivery code at the door.
make hi_en_bank_genuine Lekha "नमस्ते, मैं आपके बैंक की card services से बोल रही हूँ। आपका एक transaction decline हुआ था, कृपया bank app में check कर लीजिए। और याद रखिए, बैंक कभी भी call पर OTP या PIN नहीं माँगता, किसी को भी मत बताइए।"
make hi_en_delivery_genuine Lekha "नमस्ते sir, Flipkart delivery है, मैं आपकी building के gate पर हूँ। आपके app में order के नीचे delivery code दिख रहा होगा। Parcel लेते वक्त वो code बता देना, payment कुछ नहीं है।"
