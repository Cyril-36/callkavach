# Multilingual development pilot — review record

## Scope and lineage

Ten synthetic development calls cover scam/genuine digital-arrest and KYC pairs
in both Hindi-English and Telugu-English, plus the Telugu-English courier pair.
Each call uses an opaque ID. Evaluator-only lineage is in
`data/multilingual_pilot_ground_truth.json`; the dialogues are in
`data/multilingual_pilot_transcripts.json`. All five language/pair groups reuse
existing **development** families. None is an independent held-out family.
No held-out candidate dialogue was used to author these calls.

Raw transcript JSON is an evaluation fixture, not detector input. At replay
step N, call `detector_view(transcript, N)` and pass only that projection. It
contains language and the first N finalized segments' text and timing; it
excludes IDs, speaker, lineage, labels, ask annotations and future turns.
Ground truth must never be passed to a detector or Gemini.

No audio or detector run was performed. Segment-start times are **coarse
scripted annotations**, not measured speech, STT, or alert times. No alert
timestamp is present; obtain it only from an actual incremental detector run.

## First dangerous asks checked against the dialogue

The earlier authority claim, freeze/arrest/customs threat, secrecy and call
isolation are suspicious tactics, but do not yet request money or a banking
secret. The first dangerous request is the line below. Genuine calls have a
null ask. The courier's order-specific handoff code is not a banking OTP.

| Opaque call ID | Development family | First ask | Request |
| --- | --- | --- | --- |
| `p-4c2e9a10` | digital-arrest-scam | s7, 31,020 ms | Transfer ₹18,000 to a claimed verification account. |
| `p-0f6a52c8` | kyc-update-scam | s5, 21,280 ms | Read the banking OTP to the caller. |
| `p-a91c407e` | digital-arrest-scam | s6, 27,870 ms | Transfer ₹12,000 to a claimed verification account. |
| `p-5e3b10a7` | kyc-update-scam | s8, 32,190 ms | Read the banking OTP to the caller. |
| `p-19f0c65b` | courier-parcel-scam | s7, 30,420 ms | Transfer a ₹2,500 release fee to a supplied account. |

The Hindi digital-arrest listener starts opening a banking app and asks who
owns the account. The Hindi KYC listener reads the SMS but questions whether
to disclose it. Neither line contains a completed transfer or OTP disclosure.

## Naturalness and annotation review

Navadeep206, the author, approved an earlier four-call draft on 2026-09-29.
That approval is **not independent fluent-speaker review** of this revised
ten-call set. Independent Hindi-English and Telugu-English naturalness review
is pending. The first-ask locations above were checked against the actual
revised dialogue by the author; an independent reviewer should confirm them.
On 2026-09-29, Navadeep206 confirmed that no independent fluent reviewer is
currently available for either language. No independent accept/reject decision
or corrections can be recorded yet. This blocks completion of content review.

| Language | Independent reviewer | Naturalness | First asks and labels | Corrections / decision |
| --- | --- | --- | --- | --- |
| Hindi-English | unavailable (2026-09-29) | pending | pending | none reviewed; decision pending |
| Telugu-English | unavailable (2026-09-29) | pending | pending | none reviewed; decision pending |

Review each complete call, including code switching, hesitation, speaker turn
patterns, genuine look-alikes, labels, and whether an earlier line already
requests a dangerous action. Record the reviewer's name, date, specific
corrections and accept/reject decisions here. Structural tests cannot make
those decisions. Re-run the validator and unit tests after any edits. Do not
describe this expanded pilot as independently reviewed until that happens.
