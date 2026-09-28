# External evaluation-data audit

**Status:** research proposal for Cyril-36's review, 29 September 2026. This
report does not import external data, add calls, or freeze a test set. The
repository's 12 English development timelines remain pipeline and metric
smoke tests.

## Decision

Use [ICFD-31k](https://huggingface.co/datasets/rishia2220/icfd-31k) only as a
**separate, disclosed synthetic English/Hinglish text challenge**, subject to
its defensive-use terms. Its timestamped turns and cumulative labels can
exercise incremental replay, but neither its chunk verdicts nor synthetic
timestamps establish CallKavach's first-dangerous-ask lead time. Do not put
it into the sealed final set. [INDICA/IndiF](https://huggingface.co/datasets/vikrant-vikram/INDICA)
is **on hold** for evaluation use: its release has no stated license, a
traceable full paper or clear derivative lineage, and the inspected files do
not supply call-level timing. Neither resource replaces naturally authored
Telugu-English and Hindi-English calls or consent-based audio tests.

## Sources and inspection method

| Source | What was checked |
| --- | --- |
| [ICFD paper, IJCAI-ECAI 2026](https://www.ijcai.org/proceedings/2026/0786.pdf), [dataset card](https://github.com/SPELLAILab/ICFD-31k/blob/main/DATASET_CARD.md), [Hub release](https://huggingface.co/datasets/rishia2220/icfd-31k), [data-use terms](https://github.com/SPELLAILab/ICFD-31k/blob/main/LICENSE-DATA.md) | Paper methods/schema; author release and license; Hub metadata and visible chunk rows. Hub revision inspected: `e91937a718b4cec97b8c06820225a9bdc30dd84a`. |
| [ICFD banking normal example](https://github.com/SPELLAILab/ICFD-31k/blob/main/examples/source_conversations/banking/SCENARIO_16_Clear_Normal_1546_r1.json), [utility fraud example](https://github.com/SPELLAILab/ICFD-31k/blob/main/examples/source_conversations/utility/SCENARIO_7_Clear_Fraud_0693_r1.json), [e-commerce fraud example](https://github.com/SPELLAILab/ICFD-31k/blob/main/examples/source_conversations/ecommerce/SCENARIO_9_Clear_Fraud_0825_r1.json) | Read the three released source JSON examples, including turn timestamps, verdicts, and chunk-label progressions. These are illustrative examples, not a random sample of 31,000 calls. |
| [INDICA Hub card and file listing](https://huggingface.co/datasets/vikrant-vikram/INDICA), [Hub API metadata](https://huggingface.co/api/datasets/vikrant-vikram/INDICA), [text archive](https://huggingface.co/datasets/vikrant-vikram/INDICA/resolve/main/Text_samples.tar.gz) | Read the card, metadata and file list; range-read only the first 512 KiB of the 80.9 MB compressed text archive in memory and inspected 12 Telugu scam text files. No archive or audio was saved. Hub revision inspected: `d163a916c054111bdfb5bca4c690983a08fa9500`. This convenience slice is not a random quality estimate. |
| [TeleAntiFraud-28k paper](https://arxiv.org/abs/2503.24115) and [upstream release card](https://huggingface.co/datasets/JimmyMa99/TeleAntiFraud) | Checked the possible upstream source indicated by INDICA filenames. This does **not** establish INDICA's derivation, translation rights, or generation method. |

An exact-title search found no separately accessible INDICA/IndiF paper or
paper URL in its card as of this audit. The card supplies a BibTeX entry with
authors and year but no venue, DOI, method section, or paper link. The Hub
DOI on the page identifies the **dataset deposit**, not a verified paper.
If the authors provide a paper or methods supplement, revisit this finding.

## Dataset findings

| Question | ICFD-31k | INDICA/IndiF |
| --- | --- | --- |
| License | Hub tag is `other`; the author [data-use terms](https://github.com/SPELLAILab/ICFD-31k/blob/main/LICENSE-DATA.md) permit defensive research/evaluation and require citation, prohibit offensive use, and require written permission for commercial deployment. The repository's MIT license applies to code, **not** the data. | No Hub license metadata or LICENSE file in the inspected release tree, and no license terms in the card. Public downloadability is not a reuse grant. Obtain written terms and confirm rights in any upstream material before integration. |
| Provenance and generation | The [paper, §3](https://www.ijcai.org/proceedings/2026/0786.pdf) describes synthetic conversations generated with Llama 3.3 70B from scenario, persona and entity combinations; no real audio. About 31,000 source conversations become 1,111,071 cumulative chunk records. Synthetic names/details are stated in the [release](https://github.com/SPELLAILab/ICFD-31k). | The card calls IndiF a multilingual audio/text benchmark of 189,420 samples but does not document collection, translation, speakers, TTS system, or lineage. Inspected text filenames contain `TeleAntiFraud-28k` and `tts`; Telugu text also retains Chinese names/services. This **suggests** a derived/translated or synthesized pipeline, but the exact process and rights are unverified. The [possible source paper](https://arxiv.org/abs/2503.24115) describes ASR-derived text, LLM augmentation and TTS for TeleAntiFraud-28k; those methods cannot be assumed for INDICA. |
| Languages and mixing | Author documentation says Indian English and Hinglish. The inspected source examples mix mostly English with brief Romanized Hindi discourse markers. No Telugu or Telugu-English coverage. Rich, naturally occurring Hindi-English switching is not established by three examples. | Card lists Assamese, Bengali, English, Gujarati, Hindi, Kannada, Malayalam, Odia, Tamil and Telugu. This is language coverage, not proof of Hindi-English or Telugu-English switching *within calls*. In 12 inspected Telugu scam files, the text was overwhelmingly Telugu script with speaker markers; only isolated Latin items such as a service name appeared. Hindi and genuine examples were not sampled from the compressed archive. |
| Schema and labels | Source JSON has speaker/text/`timestamp_end` turns, final verdict, scenario/persona/entity fields, and timestamped chunk verdict/rationale. The [Hub chunk viewer](https://huggingface.co/datasets/rishia2220/icfd-31k) exposes `conversation_uid`, source batch/stem, `chunk_timestamp`, `cumulative_text`, serialized turns and final verdict. Its `chunk_timestamp` is in seconds; a visible call repeats as cumulative rows. The paper says normal calls are sparsely chunked while other cases are fully chunked, so raw chunk counts are not call counts. | The card claims scenario, fraud/non-fraud and fraud-type labels, but supplies no field schema or join key. Hub preview exposes per-clip `wav`, `__key__`, `__url__`, with paths such as `.../Audio/scam/.../Speaker2_1`; the text archive files inspected are `.txt` with `Speaker1:`/`Speaker2:` turns and a `scam` path. No timestamps, first-ask labels, or call-level pairing keys appeared in those files. The viewer's roughly 2.42 million audio rows must not be treated as 2.42 million independent calls; it differs from the card's 189,420 samples. |
| Timing and audio | Generated turn-end times and approximately 3-second cumulative chunk positions support **synthetic prefix replay**. They are not measured STT finalization, detector emission, or speech latency. No source audio for acoustic testing. Chunk verdict is the dataset's label, not our detector's alert. | Audio tar archives exist, but the visible records look like individual speaker clips, and no inspected file establishes how to reconstruct a timed complete call. The audio was not listened to in this audit; pronunciation, noise, speaker continuity and STT suitability remain unknown. Text samples have no turn timing. |
| Sample quality | The inspected banking example is a plausible lost-card service dialogue; the utility fraud example progresses from a coincidental outage to a fee demand. Both are structured, synthetic and use recognizable Hindi markers. The utility example's five chunk annotations do not by themselves supply the exact first-ask time. The e-commerce example's metadata describes a marketplace cheque situation while its opening caller claims to be from a bank; check full scenario/dialogue alignment before mapping it to our categories. The paper reports moderate inter-annotator agreement (mean pairwise κ = 0.534), which is a quality signal with limits. | The 12 Telugu scam files have roughly 9–12 speaker markers each, no timing fields, and several Chinese-context names or services despite Telugu wording. That makes them poor evidence of locally natural Telugu-English calls without native-speaker review. This observation covers only the inspected slice and says nothing conclusive about the remaining text or audio. |

The ICFD paper's 10 broad fraud umbrellas include bank/payment, e-commerce,
utility and government impersonation. Those **may** contain analogues to some
of our six scenarios, but the published umbrella names do not certify coverage
of digital arrest, courier, KYC, card block, TRAI SIM and electricity **as six
matched scam/genuine pairs**. ICFD includes normal and ambiguous cases, but
its source examples and schema do not establish family-matched benign calls.
INDICA's seven fraud types and seven ordinary scenario categories are also not
a one-to-one map to our six types. Mapping requires human review of individual
calls, not a label-name substitution. [ICFD paper](https://www.ijcai.org/proceedings/2026/0786.pdf),
[INDICA card](https://huggingface.co/datasets/vikrant-vikram/INDICA).

## What each source can measure for CallKavach

| Requirement | ICFD-31k | INDICA/IndiF |
| --- | --- | --- |
| Hindi-English text robustness | Conditional external challenge after license and subset review; label it synthetic Hinglish. | Unverified within-call mixing. |
| Telugu-English text robustness | No. | Telugu is listed, but the inspected samples do not establish Telugu-English calls. |
| Six scenario types and genuine look-alikes | Broad overlap possible; exact six-way matched coverage needs manual mapping and lineage checks. | Broad banking/delivery overlap possible; exact six-way matched coverage and genuine quality unverified. |
| Warning before first dangerous ask | **Not directly.** Human annotators must mark the first unsafe action request on source turns; chunk fraud onset is a different label. | **Not directly.** Need ordered, timed complete calls and new human first-ask annotation, neither verified in this release. |
| Audio → STT → detector performance | No audio. | Cannot claim until rights, call reconstruction and representative audio quality are checked. |

## Proposed evaluation data strategy

1. **Development and smoke checks.** Keep the 12 existing English timelines for
   input-contract and metric smoke tests only. Have fluent Telugu-English and
   Hindi-English reviewers author and review natural conversations for every
   target scenario, including ordinary support calls, negated OTP warnings,
   delivery/pickup codes, ambiguity and scam/genuine pairs. Assign each
   independent story a `pair_group_id`; keep all variants of a story in dev.
   Prompt, phrase and threshold changes use this development partition only.
2. **External checks as separate strata.** If ICFD terms fit the intended
   defensive use, select a small reviewed subset by **source conversation**,
   not by cumulative chunk. Preserve `conversation_uid`, source batch/stem,
   scenario and any generation lineage; group related personas/templates so
   no near-duplicate crosses a development/test boundary. Evaluate static
   verdicts and incremental text replay separately, reporting source-call
   counts. Do not import ICFD's chunk verdict as CallKavach's alert. Hold
   INDICA until license, upstream rights, full schema, Hindi/Telugu samples and
   timed call reconstruction are resolved. If cleared later, report it as a
   separate Indic text/audio generalization check, not as the sealed test.
3. **Sealed final evaluation.** An independent bilingual content team creates
   new scenario families, scam/genuine look-alikes and consent-based speech
   recordings outside the detector coding context. The public PR #6 outlines
   are candidate situations already exposed to developers and cannot be called
   fully blind. Freeze the detector prompt, rules, thresholds, keyword list,
   code SHA and audio/STT setup **before** releasing sealed transcripts or
   derivatives for a single evaluation run. No tuning from those outcomes.
   If the planned 300 held-out calls cannot be independently authored and
   reviewed, report the smaller actual set instead of inflating it with
   paraphrases.
4. **Lineage and annotation contract.** For every call retain `call_id`,
   `family_id`, `pair_group_id`, source dataset/revision/record, original
   script or prompt lineage, derivation type, speaker identity when relevant,
   language(s), scenario, label, and split. Keep truth (`label`,
   `first_ask_at_ms`) separate from detector input. A fluent reviewer marks
   the *start of the first caller request* for money/transaction approval,
   credentials or activation codes, remote access, or sensitive ID transfer
   through an unverified channel. Record null for genuine calls; adjudicate
   disputes and document policy changes before the final run. Every
   translation, paraphrase, voice rendering and chunk of the same source
   family inherits its split. Audit family IDs and source lineage across
   partitions before scoring.
5. **Incremental replay and reporting.** Feed only ordered finalized segments
   available at each step to the detector, deduplicate repeated windows, and
   keep source labels, rationales and future turns out of its input. For ICFD,
   reconstruct new text from cumulative chunks or use source turns; do not
   replay a whole cumulative transcript as a new segment each time. For
   human audio, measure actual STT finalization and **emitted red-alert**
   timestamps; never fabricate them from script or chunk labels. Report scam
   recall, genuine false-alarm rate, warned-before-ask rate, median alert
   time, misses and errors with both call counts and independent-family
   counts, broken down by language, scenario, source and text/audio mode.

## Owner decisions before data integration

- Confirm whether the intended use fits ICFD's defensive-only data terms;
  seek author permission if commercial deployment is planned.
- Ask INDICA authors for license, paper/methods, TeleAntiFraud lineage and
  derivative rights, text/audio pairing keys, split provenance, and an
  example complete Hindi and Telugu call with timing.
- Approve a native-speaker review rubric and independently sealed final
  family plan before generating or acquiring evaluation calls.

No bulk dataset download, dataset commit, call generation, or detector run was
performed for this report.
