# Deploying CallKavach

The relay and the listener app run as **one container** (`Dockerfile`). It needs a host that:
- terminates **HTTPS**, because phones only give a page microphone access over https;
- supports **long-lived WebSockets**, since a session can last up to 15 minutes;
- runs a **single instance**, because session limits are held in memory.

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
| `CALLKAVACH_ACCESS_CODE` | A code you give to testers and judges. Without it, anyone with the link spends your credits |
| `CALLKAVACH_MAX_SESSIONS_PER_HOUR` | For example `20`. A server-wide cap on sessions that reach Sarvam or AICredits |

| `CALLKAVACH_EVAL_REPORT_JSON` *(optional)* | The contents of a public evaluation export (`node frontend/app/export-eval-report.mjs RAW.json PUBLIC.json`), shown in the Evaluation tab. Alternatively, set `CALLKAVACH_EVAL_REPORT` to a file path outside the repository. The server refuses anything that isn't the sanitised public form |

The host sets `PORT`.

**The relay refuses to start (`ConfigError`) when:**
- `CALLKAVACH_PUBLIC_HOSTS` is set without both a non-empty `CALLKAVACH_ACCESS_CODE` and `CALLKAVACH_MAX_SESSIONS_PER_HOUR`, so a forgotten secret can't expose the paid providers; or
- `CALLKAVACH_MAX_SESSIONS_PER_HOUR` is anything but a positive integer.

## What the relay checks on a public host

- **Host and Origin:** the Host must be listed in `CALLKAVACH_PUBLIC_HOSTS`, with no port or port 443, and the browser's Origin must be exactly `https://` plus that host. Anything else, including a client without an Origin, is refused before a session opens.
- **Access code:** a missing or wrong code is refused before any provider connection, with a 1 s delay.
- **Hourly cap:** when it's reached, new sessions are refused before any provider connection.
- **Existing limits:** 4 concurrent sessions, 15 minutes and 5 s of queued audio per session.

The Origin check and a shared code are not strong authentication. They're meant to stop casual misuse during the demo. Rotate the code if it leaks, and take the service down after judging.

## Monitoring

The relay logs one line per event to stdout, which most hosts show in their log view. It never logs the access code, audio or transcripts:

| Log line | Meaning |
|---|---|
| `session_started` | A paid session opened |
| `access_denied` | A wrong or missing code |
| `session_quota` | The hourly cap was reached |
| `too_many_sessions` | More than 4 sessions at once |
| `idle_timeout` | A client went silent for 30 s |
| `refused_upgrade` | Wrong Host or Origin |

A burst of `access_denied` or `refused_upgrade` lines means someone is probing. Rotate the code, and lower the cap or take the service down.

## If it stays online after the demo

The shared code, Origin check and in-memory hourly cap are meant for a short, supervised demo. For longer use, follow the [OWASP WebSocket Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html) and add:
- **Per-user authentication:** a short-lived signed token per user, checked at the upgrade, instead of one shared code.
- **Per-client rate limits:** per IP or per token, at the proxy or in a shared store (Redis), so the limits survive restarts and multiple instances.
- **Abuse monitoring and alerting:** alerts on the log lines above, plus provider-side spend alerts on Sarvam and AICredits.
- **A privacy notice and consent flow** suitable for real calls, and a data-processing review of the providers' retention.

## After deploying

1. **Check the app loads.** Open `https://<host>/` on a laptop, enter the access code in **Settings**, and run one **sample** (a paid call). It should finish "fully analysed".
2. **Run the phone test.** Open `https://<host>/` on a phone, allow the microphone, and test as a second device next to a speakerphone playing synthetic or consented audio. Record results in `docs/qa-and-submission.md`.
3. **Check the free test page.** `/lifecycle.test.html` drives the app with a synthetic microphone. On a deployed server it uses the real providers and costs credits, so run it locally with `STT_PROVIDER=mock LLM_PROVIDER=off` instead.
