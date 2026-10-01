# Deploying CallKavach

The relay and the listener app run as **one container** (`Dockerfile`). It needs a host that:
- terminates **HTTPS**, because phones only give a page microphone access over https;
- supports **long-lived WebSockets**, since a session can last up to 15 minutes;
- runs a **single instance**, because concurrent-session state is held in memory.

Render, Railway, Fly.io and Google Cloud Run all work. Serverless function hosts such as Vercel functions do not.

## Settings

Put these in the host's secret or environment settings, never in Git or the image:

| Variable | Value |
|---|---|
| `SARVAM_API_KEY` | Sarvam key (speech-to-text) |
| `LLM_PROVIDER` | `aicredits` |
| `AICREDITS_API_KEY` | AICredits key |
| `AICREDITS_MODEL` | `gemini-2.5-flash` |
| `CALLKAVACH_PUBLIC_HOSTS` | The public host name only, for example `callkavach.onrender.com` (no `https://`, no path) |
| `CALLKAVACH_MAX_SESSIONS_PER_HOUR` *(optional)* | A server-wide hourly cap on paid sessions. Leave unset for the short testing period to avoid a five-session lockout |
| `CALLKAVACH_EVAL_REPORT_JSON` *(optional)* | The contents of a public evaluation export (`node frontend/app/export-eval-report.mjs RAW.json PUBLIC.json`), shown in the Evaluation tab. Alternatively, set `CALLKAVACH_EVAL_REPORT` to a file path outside the repository. The server refuses anything that isn't the sanitised public form |

The host sets `PORT`.

If `CALLKAVACH_MAX_SESSIONS_PER_HOUR` is set, it must be a positive integer or the relay refuses to start.

## What the relay checks on a public host

- **Host and Origin:** the Host must be listed in `CALLKAVACH_PUBLIC_HOSTS`, with no port or port 443, and the browser's Origin must be exactly `https://` plus that host. Anything else, including a client without an Origin, is refused before a session opens.
- **Optional hourly cap:** when configured and reached, new sessions are refused before any provider connection.
- **Existing limits:** 4 concurrent sessions, 15 minutes and 5 s of queued audio per session.

This public test has no access code or hourly cap. Anyone with the link can start paid sessions, and a non-browser client can forge an Origin header. Monitor provider usage and take the service down after judging.

## Monitoring

The relay logs one line per event to stdout, which most hosts show in their log view. It never logs audio or transcripts:

| Log line | Meaning |
|---|---|
| `session_started` | A paid session opened |
| `session_quota` | The optional hourly cap was reached |
| `too_many_sessions` | More than 4 sessions at once |
| `idle_timeout` | A client went silent for 30 s |
| `refused_upgrade` | Wrong Host or Origin |

A burst of `session_started` or `refused_upgrade` lines may mean someone is using the public test unexpectedly. Take the service down if usage is not expected.

## If it stays online after the demo

The Origin check alone is suitable only for a short, supervised test. For longer use, follow the [OWASP WebSocket Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html) and add:
- **Per-user authentication:** a short-lived signed token per user, checked at the upgrade.
- **Per-client rate limits:** per IP or per token, at the proxy or in a shared store (Redis), so the limits survive restarts and multiple instances.
- **Abuse monitoring and alerting:** alerts on the log lines above, plus provider-side spend alerts on Sarvam and AICredits.
- **A privacy notice and consent flow** suitable for real calls, and a data-processing review of the providers' retention.

## After deploying

1. **Check the app loads.** Open `https://<host>/` on a laptop. A sample run uses paid providers; run one only when needed and confirm that it finishes "fully analysed".
2. **Run the phone test.** Open `https://<host>/` on a phone, allow the microphone, and test as a second device next to a speakerphone playing synthetic or consented audio. Record results in `docs/qa-and-submission.md`.
3. **Check the free test page.** `/lifecycle.test.html` drives the app with a synthetic microphone. On a deployed server it uses the real providers and costs credits, so run it locally with `STT_PROVIDER=mock LLM_PROVIDER=off` instead.
