# Proposed held-out family outlines

**Status: public candidate set, for Cyril-36's revised review.** The 12 records in
`data/heldout_family_outlines.json` are six proposed scam/genuine pair groups,
one per existing scenario type. They are outlines, not calls or a frozen split
manifest. Every pair uses one `pair_group_id`; each record has a stable
`family_id`. Step order is the JSON array order, and
`first_dangerous_ask_step` is a zero-based index into that array. Genuine
records have a null ask step.

| Pair group | New situation and evidence progression | Difference from development seed | Scam's first dangerous ask |
| --- | --- | --- | --- |
| `digital-arrest-heldout-01` | Unexpected virtual court notice, claimed clerk transfer, then a private video-hearing confinement demand | Dev uses an alleged illegal transfer and asks for a savings transfer; this asks for device control | Step 3: install screen-sharing app and grant control |
| `courier-parcel-heldout-01` | Incomplete address at a sorting hub, partial tracking detail, then a redelivery link | Dev uses a customs/prohibited-item allegation and a release fee; this uses routine address repair to capture card data | Step 2: enter card details in caller-supplied link |
| `kyc-update-heldout-01` | Customer's wallet address change becomes a claimed video-KYC review | Dev uses an unsolicited bank-account freeze and OTP request; this seeks ID images through an outside link | Step 3: upload ID images and selfie to caller-supplied link |
| `bank-card-block-heldout-01` | Lost card already reported blocked, then a claim that online payments remain exposed | Dev starts with a suspicious transaction and offers immediate unblocking; this exploits a customer-initiated block | Step 2: authorize a 1,999-rupee UPI collect payment disguised as card-security verification |
| `trai-sim-disconnection-heldout-01` | Claimed duplicate eSIM request, activation threatens the current SIM, then a fake cancellation | Dev claims a regulator complaint and requests remote access; this seeks an activation code | Step 3: read the carrier activation code |
| `electricity-bill-heldout-01` | Meter-reading dispute becomes a claimed account mismatch and fake inspection ticket | Dev uses an overdue bill and personal UPI payment; this uses a complaint workflow to seek screen access | Step 3: install app and enable screen sharing |

The genuine side of each pair covers the same broad topic through a
customer-initiated inquiry or request and an independently checkable service
path. Four end with routine next steps rather than an anti-fraud statement.
The KYC and eSIM genuine calls retain explicit warnings as hard negative
examples, and the courier genuine call uses an ordinary pickup code. These
details should not become label shortcuts in a final test.

## Dangerous-ask annotation policy

`first_dangerous_ask_step` is the first step where the caller asks the listener
to take an unsafe action, not the first suspicious clue. Count requests to
transfer or authorize money, disclose banking/card/activation secrets, grant
remote device control, or send sensitive identity material through an
unverified caller-supplied channel. The wallet KYC request for both sides of
an ID card and a live selfie through such a link counts, as does the request
to reveal an eSIM activation code. The lost-card case asks the listener to
authorize a UPI collect payment disguised as card-security verification;
that is a money-transfer request. Isolation, claimed
authority, urgency, a fake case number, and a threat of disconnection are
suspicious tactics but do not by themselves set the dangerous-ask index.
Benign requests such as checking an existing app, bringing a pickup code to a
counter, or keeping a complaint reference do not count. In full transcripts,
the first-ask timestamp must be annotated from the actual caller turn, not
calculated from these outline indices.

## Independence and split review

The table above records the author-side comparison of each candidate with its
development seed: underlying event, evidence order, and requested action.
Cyril-36's content review supplied with the requested changes found the six
new situations meaningfully different, while withholding approval over
evaluation design. That review is not a frozen-split decision. The owner must
confirm each revised pair's independence before a manifest is frozen; a
structural validator cannot decide semantic independence.

`python3 backend/evaluation/validate_heldout_families.py` checks that the
development and candidate sets each contain six intact scam/genuine pairs,
with unique family IDs, distinct pair-group IDs across sets, and no
development/candidate family-ID overlap. The paired labels and all future
derivatives must stay together in the eventual split.

These outlines are visible in a public PR, so this candidate set is **not a
fully blind held-out test**. If these candidates are used for evaluation,
disclose that exposure. A fully blind scenario test needs separately authored,
sealed families. Final transcripts and derivatives must stay outside the
coding agent's development context until the detector prompt, rules, and
thresholds are frozen. Do not use candidates or sealed material as dev
exemplars or for tuning. Run each final call once through the same incremental
detector interface, record actual alert timestamps, and report both call and
independent-family counts.

No complete transcripts, translations, paraphrases, recordings, detector
outputs, or 300-call dataset are included.
