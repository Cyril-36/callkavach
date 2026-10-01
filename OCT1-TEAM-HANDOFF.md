# 1 October handoff — CallKavach

The submission deadline is **1 October 2026, 11:59 PM IST**. Aim to submit by 8 PM. This handoff supersedes the older teammate allocation for today's remaining work; the confirmed product and safety requirements in `CallKavach-Build-Plan.md` still apply.

**Cyril owns all frontend code and UI integration.** The remaining non-frontend work is split into two roughly equal work packages, estimated at 5–6 focused hours each. Cyril's frontend work is additional. Prefer a smaller measured, honest submission over an unreviewed 300-call claim.

| Owner | Non-frontend work | Deliverable and acceptance |
| --- | --- | --- |
| Harshit (`Harshit-ambati`) | Warning wording and offline audio assets; independent Hindi/Telugu pilot review; mock and device QA; submission evidence and PR review | `harshit.md` defines exact files, checks and deadlines. No API keys or live-provider calls. |
| Cyril (`Cyril-36`) | Review and integrate backend PRs; choose Stop behavior; run Sarvam and configured verifier checks; deploy and verify the live service; produce measured evaluation export; final submission | An approved integrated commit, a fresh-audio two-device warning, an honestly labelled evaluation report, working public link and submission receipt. |

## Merge authority and boundary

Harshit has a pending invitation to collaborate on the public repository. After **he accepts**, collaborator write access allows him to merge eligible pull requests. The existing `main` rule still requires a PR, one current approval, code-owner review, approval of the latest push and resolved conversations. `CODEOWNERS` keeps Cyril as the code owner of all files. Harshit may operate the merge button for a teammate PR **only after Cyril has reviewed and approved its current head**, checks pass, and the PR is ready. Harshit does not merge his own PR or bypass branch protection. Cyril remains responsible for deciding whether code and logic match the project. Do not grant administrator or bypass access or weaken the rule for this handoff.

## Sequence and handoffs

1. **Now–1 PM:** Cyril reviews PR #12 and the Stop cut-off; Harshit reviews its non-API logic and starts warning wording. Treat a cut-off as pending, not a clean negative. Both can work in parallel on separate branches.
2. **By 4 PM:** Harshit hands over reviewed warning text and playable offline clips, plus language-review notes. Cyril integrates the warning experience in the frontend and runs the first deployed fresh-audio test with server-side keys.
3. **By 6 PM:** Cyril runs a bounded development evaluation and exports the actual counts and failures; Harshit independently checks wording, labels, the evidence table and a mock/device QA checklist. PR #11 stays draft until its runner and measured output are reviewed.
4. **By 8 PM target:** Cyril verifies the public URL, demo, README and final submission fields and submits. Harshit checks links and claims, and merges eligible teammate PRs only under the rule above.

The number of reviewed calls, language coverage, speaker overlap, provider failures, Stop cut-offs, and timing basis must be explicit. Synthetic text replay is not audio latency. Do not put API keys, real call transcripts or consented recordings in the public repository.
