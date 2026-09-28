# Agent instructions for CallKavach

Read `CLAUDE.md`, `CallKavach-Build-Plan.md`, and `CONTRIBUTING.md` before changing project code. The owner is `Cyril-36`; `main` is protected and the owner reviews teammate changes. Keep credentials and real call material out of Git.

## If you are working for Navadeep

Read `navadeep.md` as the complete task brief. Your assignment is the offline Python evaluation module under `backend/evaluation/`, approximately 15–20% of the planned backend. The main implementer owns audio capture, STT, tactic detection, Gemini verification, risk accumulation, WebSocket transport, frontend, deployment, and integration. Do not take on those modules or revise the warning policy.

Before coding, check the latest `main` and confirm the target files are not already being changed in your checkout. Implement the exact interfaces and acceptance tests in `navadeep.md`. If an interface conflicts with new code, document the conflict in your PR and ask the owner to decide; do not silently change unrelated files. Use only synthetic data in tests. Do not require live API calls or credentials to run your tests.

Commit and push on `navadeep/backend-evaluation` under Navadeep's own configured Git identity. Stage only `backend/evaluation/`. Run the specified tests and `git diff --cached --check`, inspect the staged diff for secrets and scope, then commit with a descriptive message. Open a PR targeting `main`, request `Cyril-36` as reviewer, and leave it unmerged. When addressing feedback, push additional commits to the same branch; the branch rule requires fresh approval after new commits.

## If you are working on another assignment

Follow that assignment's explicit scope. The Navadeep file does not authorize changes outside his module. Keep teammate contributions in branches and let the owner approve and merge pull requests.
