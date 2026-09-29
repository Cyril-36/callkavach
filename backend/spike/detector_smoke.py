"""Live smoke test: run short SYNTHETIC conversations through SessionDetector with the configured provider.

Every line below was written for this check. The two scam calls reuse the exact Sarvam transcripts of this
repo's synthetic TTS samples (backend/spike/make_samples.sh), including Sarvam's recognition errors. None
of this comes from backend/evaluation/ data. Makes real, billed API calls.

Usage: uv run --no-project --with httpx python backend/spike/detector_smoke.py [--timeout 30] [--json out.json]
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from detector import Segment, SessionDetector  # noqa: E402
from verifier_config import make_verifier  # noqa: E402

CONVERSATIONS = {
    "hi_en_scam": ("scam, credential request", [
        # Sarvam's actual output for hi_en_kyc.wav: "KYC" misheard as "कार्ड", English in Devanagari.
        "मैं स्टेट बैंक के कार्ड डिपार्टमेंट से बोल रहा हूँ,",
        "आपका अकाउंट आज ब्लॉक हो जाएगा,",
        "अभी जो ओटीपी आया है वो बताइए।",
    ]),
    "te_en_scam": ("scam, digital arrest", [
        # Sarvam's actual output for te_en_digital_arrest.wav, split at sentence ends ("Cyber" misheard).
        "నేను Mumbai Cibir Crime నుండి Inspector Sharma మాట్లాడుతున్నాను.",
        "మీ పేరు మీద ఒక parcel-లో drugs మరియు fake passports దొరికాయి.",
        "ఎవరికీ చెప్పకండి. call-లోనే ఉండండి.",
    ]),
    "negated_otp_warning": ("genuine, negated OTP warning", [
        "Hello sir, main aapke bank ke card services se bol rahi hoon, aapka ek transaction decline hua tha.",
        "Aap apne bank app mein jaake transaction check kar lijiye.",
        "Aur please yaad rakhiye, bank kabhi bhi call pe OTP ya PIN nahi maangta, kisi ko bhi share mat kijiye, mujhe bhi nahi.",
    ]),
    "delivery_code_genuine": ("genuine, delivery code", [
        "Hello sir, Flipkart delivery hai, main aapke building ke gate pe khada hoon.",
        "Aapke app mein order ke neeche ek delivery code dikh raha hoga.",
        "Main door pe aata hoon, parcel lete waqt woh code bata dena, payment kuch nahi hai, prepaid hai.",
    ]),
}


async def run_conversation(verifier, lines, timeout_s):
    events = []

    async def emit(e):
        events.append(e)
    d = SessionDetector(verifier, emit, min_interval_s=0.0, call_timeout_s=timeout_s)
    per_segment = []
    for i, text in enumerate(lines):
        before = len(events)
        t0 = time.perf_counter()
        d.add(Segment(f"s{i}", text, i * 5000))
        while not d.idle():
            await asyncio.sleep(0.05)
        e = events[-1] if len(events) > before else None
        per_segment.append({
            "segment": f"s{i}", "wall_s": round(time.perf_counter() - t0, 2),
            "analysis": e and e["analysis"], "level": e and e["level"], "error": e and e["error"],
            "rejected_findings": e and e["rejected_findings"],
            "tactics": e and {t["tactic"]: [q["quote"] for q in t["evidence"]] for t in e["tactics"]},
            "verifier": e and e["verifier"],
        })
    await d.close()
    return per_segment, d.summary()


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--timeout", type=float, default=30.0, help="per-call timeout for measurement (production: 8 s)")
    p.add_argument("--json", help="write full results here")
    p.add_argument("--only", nargs="*", help="conversation names to run")
    args = p.parse_args()
    verifier, why = make_verifier()
    if not verifier:
        print(f"BLOCKED: {why}", file=sys.stderr)
        return 2
    print(f"provider={verifier.provider} model={verifier.model} measurement timeout={args.timeout:g}s\n")
    results = {}
    for name, (kind, lines) in CONVERSATIONS.items():
        if args.only and name not in args.only:
            continue
        segments, summary = await run_conversation(verifier, lines, args.timeout)
        results[name] = {"kind": kind, "segments": segments, "summary": summary}
        print(f"== {name} ({kind})")
        for s in segments:
            v = s["verifier"] or {}
            print(f"  {s['segment']}: {s['wall_s']:5.2f}s  analysis={s['analysis']} level={s['level']} "
                  f"rejected={s['rejected_findings']} model={v.get('returned_model')} finish={v.get('finish_reason')} "
                  f"cost={v.get('cost')} tokens={v.get('prompt_tokens')}/{v.get('completion_tokens')}")
            if s["error"]:
                print(f"      error: {s['error']}")
            if s["tactics"]:
                print(f"      tactics: {json.dumps(s['tactics'], ensure_ascii=False)}")
        print(f"  final: level={summary['level']} status={summary['status']} tactics={summary['tactics']}\n")
    await verifier.close()
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
