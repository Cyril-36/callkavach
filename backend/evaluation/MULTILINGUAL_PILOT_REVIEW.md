# Multilingual development pilot — candidate review

## Scope and lineage

This is a **draft development pilot**, not a held-out set or a detector result.
It contains one Hindi-English KYC scam/genuine pair and one Telugu-English
courier scam/genuine pair. The calls descend from the existing development
families `kyc-update-seed-01` and `courier-parcel-seed-01`; these are not
independent new families. They must stay on the development side of the split.
The public held-out candidate outlines and any sealed final test are excluded.

The two JSON files have different uses:

* `data/multilingual_pilot_transcripts.json`: detector input; finalized segments
  only, with ordered **synthetic** timeline timestamps.
* `data/multilingual_pilot_ground_truth.json`: evaluator-only family lineage,
  labels, and first-dangerous-ask annotations. Never send it to the detector.

No audio was recorded. The timestamps approximate scripted turn boundaries,
not measured speaking or STT latency. There are no alert timestamps; obtain
them only from incremental detector replay of the finalized segment stream.

## Annotation choices to review

| Call | Proposed label | Proposed first ask | Rationale |
| --- | --- | --- | --- |
| `pilot-hi-en-kyc-scam-001` | scam | 27,600 ms, s7 | Caller first requests the banking OTP. The earlier freeze claim and urgency are tactics, not a dangerous action request. |
| `pilot-hi-en-kyc-genuine-001` | genuine | null | Branch/app appointment; caller explicitly rejects sharing an OTP. |
| `pilot-te-en-courier-scam-001` | scam | 28,900 ms, s7 | Caller first requests a ₹2,500 transfer to a supplied account. Earlier customs/police pressure is a tactic. |
| `pilot-te-en-courier-genuine-001` | genuine | null | Order-specific delivery code is requested only after parcel handoff, not a banking credential or payment. |

## Human review gate

Navadeep206 was nominated to review both languages. **Review is pending.**
For each call, read the complete dialogue and record corrections before
acceptance:

1. Does the wording sound like a plausible local phone call, including the
   Hindi-English or Telugu-English switching? Correct unnatural expressions.
2. Are the speaker turns, intent progression, label, and family lineage right?
3. Does any segment **before** the annotated ask already request money, a
   banking secret, identity transfer to an unverified destination, remote
   access, or another dangerous action? If so, move the annotation.
4. Does the genuine call contain a realistic benign look-alike without a
   dangerous ask? In particular, distinguish an order handoff code from a bank
   OTP and a protective OTP warning from a request to disclose it.
5. After wording edits, check the synthetic segment durations remain plausible.

| Language | Reviewer | Naturalness | Labels and first asks | Corrections / date |
| --- | --- | --- | --- | --- |
| Hindi-English | Navadeep206 | pending | pending | pending |
| Telugu-English | Navadeep206 | pending | pending | pending |

Do not call this pilot human-reviewed, scale it, or treat its scores as final
until the reviewer fills these decisions. Run `python3
backend/evaluation/validate_multilingual_pilot.py` after every correction,
then run the evaluation unit tests. Structural validation cannot judge
linguistic naturalness or semantic first-ask accuracy.
