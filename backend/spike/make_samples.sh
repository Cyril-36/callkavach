#!/usr/bin/env bash
# Generate synthetic code-mixed test audio with macOS voices (no real call material).
# Output: 16 kHz, mono, 16-bit PCM WAV in backend/spike/samples/ (committed, so a deployed server has them).
# Usage: bash make_samples.sh             builds every sample
#        bash make_samples.sh NAME ...    builds only those samples
# [[slnc 1000]] inserts a 1 s pause, so the speech-to-text finalizes sentence by sentence as on a real call.
set -euo pipefail
ONLY="$*"
cd "$(dirname "$0")"
mkdir -p samples

make() {  # name voice text
  if [ -n "$ONLY" ] && [[ " $ONLY " != *" $1 "* ]]; then return; fi  # not one of the requested names
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

# --- More synthetic calls (1 October): sentence pauses, four scams and three genuine look-alikes. ---
P="[[slnc 1000]]"
# Hindi-English scam: UPI "refund" that asks the listener to approve a collect request with their PIN.
make hi_en_upi_refund Lekha "Hello sir, मैं Amazon customer care से बोल रहा हूँ। $P आपके पिछले order का दो हज़ार रुपये का refund pending है। $P मैंने आपके PhonePe पर एक request भेजी है, उसे approve करके अपना UPI PIN डाल दीजिए। $P पैसे तुरंत आपके account में आ जाएँगे, जल्दी कीजिए, ये आज ही valid है।"
# Hindi-English scam: part-time "task" job with a registration fee (no credential request: a harder case).
make hi_en_job_fee Lekha "Hi, मैं HR team से बोल रही हूँ, आपका profile part-time job के लिए select हुआ है। $P रोज़ YouTube videos like करके आप तीन हज़ार रुपये कमा सकते हैं। $P Start करने के लिए बस एक हज़ार रुपये registration fee UPI पर भेजनी होगी। $P आज ही भेजिए, seats limited हैं।"
# Telugu-English scam: electricity disconnection threat, app install and payment.
make te_en_power_cut_scam Geeta "నమస్కారం, నేను electricity department నుండి మాట్లాడుతున్నాను. $P మీ last month bill update కాలేదు, ఈ రోజు రాత్రి తొమ్మిది గంటలకు మీ connection కట్ అవుతుంది. $P వెంటనే నేను పంపిన AnyDesk app install చేయండి, నేను మీ phone లో bill update చేస్తాను."
# Telugu-English scam: courier parcel held at customs, police threat, secrecy and a "fine".
make te_en_customs_parcel Geeta "Hello, నేను FedEx courier నుండి మాట్లాడుతున్నాను. $P మీ పేరు మీద Mumbai customs దగ్గర ఒక parcel ఆగిపోయింది, అందులో illegal items ఉన్నాయి. $P ఇది police case అవుతుంది, ఈ విషయం ఎవరికీ చెప్పకండి. $P case close చేయడానికి ఇప్పుడే ఇరవై వేల రూపాయలు fine కట్టాలి."
# Hindi-English genuine: loan EMI reminder from a named bank (a deadline and a late fee, nothing sensitive asked).
make hi_en_emi_reminder Lekha "नमस्ते, मैं HDFC Bank के loan department से बोल रही हूँ। $P आपकी car loan की इस महीने की EMI तीन तारीख को due है। $P कृपया account में balance रखिए, वरना late fee लग सकती है। $P Payment आप bank app से या branch में कर सकते हैं, हम कभी OTP या PIN नहीं माँगते।"
# Telugu-English genuine: planned maintenance power cut, nothing to pay.
make te_en_power_cut_notice Geeta "నమస్కారం, ఇది TSSPDCL నుండి call. $P రేపు ఉదయం పది నుండి మధ్యాహ్నం రెండు వరకు మీ area లో maintenance పని కారణంగా power cut ఉంటుంది. $P దీనికి మీ bill తో సంబంధం లేదు, మీరు ఏమీ pay చేయాల్సిన అవసరం లేదు."
# Telugu-English genuine: bank complaint callback, card replacement, never share OTP.
make te_en_bank_callback Geeta "Hello sir, నేను SBI customer care నుండి మాట్లాడుతున్నాను, మీరు నిన్న complaint ఇచ్చారు కదా. $P మీ card replacement request process అయ్యింది, కొత్త card ఒక వారంలో మీ address కి వస్తుంది. $P ఏ OTP కూడా ఎవరికీ చెప్పకండి, మేము ఎప్పుడూ అడగము."
