# Contributing to CallKavach

The owner, `Cyril-36`, is responsible for integration and the final submission. Do not push directly to `main`.

1. Start from the latest `main` and create a branch such as `feature/telugu-warning-copy` or `fix/audio-resampling`.
2. Keep the change within the assigned task. Include the input or scenario used to verify the logic.
3. Push the branch and open a pull request targeting `main`; mark it draft until ready.
4. Fill in the pull request template, including a concrete before/after example and any tests or manual checks.
5. Request `Cyril-36` as reviewer. Address review comments with new commits. Do not merge your own pull request.
6. The owner checks alignment with the [confirmed plan](CallKavach-Build-Plan.md), reviews the code and logic, verifies the relevant test and merges only after approval.

Keep credentials, real call audio and ordinary users' transcripts out of Git. Use synthetic or explicitly consented evaluation data with clear labels. Do not change warning thresholds or claims in the dashboard without updating the evaluation evidence.

GitHub's active branch protection is the enforcement mechanism. `CODEOWNERS` designates `Cyril-36` as the required reviewer. Do not grant teammates administrator or bypass privileges.
