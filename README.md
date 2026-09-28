# CallKavach

CallKavach is a hackathon prototype for PS-06, AI for Bharat in Indian Languages. A second device listens to a doubtful speakerphone call and warns the listener in their language when verified scam tactics appear. The final submission deadline is **1 October 2026, 11:59 PM IST**.

The [confirmed implementation plan](CallKavach-Build-Plan.md) defines the build order, evidence rules, evaluation, dashboard and cut order. The repository currently contains planning and collaboration setup; it does not yet contain a working listener.

## Intended layout

- `frontend/`: React listener, demo and evaluation views; browser audio capture.
- `backend/`: FastAPI transport, speech integration, detection and warning events.
- `evaluation/`: scenarios, baseline, metrics and exported results.
- `docs/`: architecture and submission evidence.

Create these folders when the first code for each area is ready. Keep API keys in a local `.env`, never in Git. `.env.example` lists the expected names without values.

## Contributions and approvals

`main` is the integration branch. Teammates work on their own branches and open pull requests into `main`. The repository owner, **Cyril-36**, reviews the code, logic, evidence and tests before merging. The [contribution guide](CONTRIBUTING.md) and pull request template make that review explicit. GitHub branch protection is active: it requires a pull request, one approval, a code-owner review, fresh approval after changes, approval of the latest push and resolved review conversations. Force pushes and branch deletion are disabled. The owner is an administrator and can bypass this classic rule for their own integration work; teammates should have collaborator access only.

No automatic merge is authorized. A passing check is necessary but does not replace the owner's review of the logic.
