# Proposed held-out family outlines

**Status: for Cyril-36's review.** The 12 records in
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
| `bank-card-block-heldout-01` | Lost card already reported blocked, then a claim that online payments remain exposed | Dev starts with a suspicious transaction and offers immediate unblocking; this exploits a customer-initiated block | Step 2: reveal full card number and CVV |
| `trai-sim-disconnection-heldout-01` | Claimed duplicate eSIM request, activation threatens the current SIM, then a fake cancellation | Dev claims a regulator complaint and requests remote access; this seeks an activation code | Step 3: read the carrier activation code |
| `electricity-bill-heldout-01` | Meter-reading dispute becomes a claimed account mismatch and fake inspection ticket | Dev uses an overdue bill and personal UPI payment; this uses a complaint workflow to seek screen access | Step 3: install app and enable screen sharing |

The genuine side of each pair covers the same broad topic through a
customer-initiated inquiry or request and an independently checkable service
path. That makes the pair a closer benign comparison without repeating the
development seed's call flow. The paired labels and any future derivatives
must remain together in the eventual split. The owner should judge whether
each new situation and progression is independent enough before freezing the
manifest; structural validation cannot establish independence.

No complete transcripts, translations, paraphrases, recordings, detector
outputs, or 300-call dataset are included. These outlines must not be used as
dev exemplars or for detector tuning if the owner accepts them as held-out.
