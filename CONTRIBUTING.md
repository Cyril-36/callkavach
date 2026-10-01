# Contributing to CallKavach

The owner, `Cyril-36`, is responsible for integration and the final submission. Do not push directly to `main`.

1. Start from the latest `main` and create a branch such as `feature/telugu-warning-copy` or `fix/audio-resampling`.
2. Keep the change within the assigned task. Include the input or scenario used to verify the logic.
3. Push the branch and open a pull request targeting `main`; mark it draft until ready.
4. Fill in the pull request template, including a concrete before/after example and any tests or manual checks.
5. Request `Cyril-36` as reviewer. Address review comments with new commits. Do not merge your own pull request.
6. The owner checks alignment with the [confirmed plan](CallKavach-Build-Plan.md), reviews the code and logic, and verifies the relevant tests. For the 1 October handoff, Harshit may operate the merge for another teammate's PR after the owner's current code-owner approval and all branch requirements are satisfied. Authors do not merge their own PRs.

Keep credentials, real call audio and ordinary users' transcripts out of Git. Use synthetic or explicitly consented evaluation data with clear labels. Do not change warning thresholds or claims in the dashboard without updating the evaluation evidence.

GitHub's active branch protection is the enforcement mechanism. `CODEOWNERS` designates `Cyril-36` as the required reviewer. Do not grant teammates administrator or bypass privileges. See [the 1 October handoff](OCT1-TEAM-HANDOFF.md) for the temporary work split and merge procedure.
