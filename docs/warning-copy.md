# Warning copy and offline clips

These are short, generic messages for an **amber** or **red** event. The event's on-screen evidence must supply the specific reason; these clips do not claim that a crime occurred or that the caller's identity is known. An analysis failure must be shown separately and must not play a reassuring message. Cyril owns playback and frontend integration.

| Level | Language | Spoken text | Clip |
| --- | --- | --- | --- |
| Amber | Hindi | इस कॉल में कुछ चिंताजनक संकेत मिले हैं। कोई पैसा या जानकारी देने से पहले, कॉल रोककर आधिकारिक नंबर से जाँच करें। | `assets/warnings/amber-hi.wav` |
| Red | Hindi | इस कॉल में गंभीर जोखिम के संकेत मिले हैं। अभी पैसा या बैंकिंग जानकारी साझा न करें। कॉल काटकर किसी भरोसेमंद व्यक्ति से मदद लें। | `assets/warnings/red-hi.wav` |
| Amber | Telugu | ఈ కాల్‌లో కొన్ని ఆందోళనకరమైన సూచనలు కనిపించాయి. డబ్బు లేదా సమాచారం ఇచ్చే ముందు, కాల్ ఆపి అధికారిక నంబరుతో ధృవీకరించండి. | `assets/warnings/amber-te.wav` |
| Red | Telugu | ఈ కాల్‌లో తీవ్రమైన ప్రమాద సూచనలు కనిపించాయి. ఇప్పుడు డబ్బు లేదా బ్యాంకింగ్ వివరాలు పంచుకోవద్దు. కాల్ ముగించి నమ్మకమైన వ్యక్తి సహాయం తీసుకోండి. | `assets/warnings/red-te.wav` |
| Amber | English fallback | This call has shown some warning signs. Pause before sharing money or information, and verify through an official number. | `assets/warnings/amber-en.wav` |
| Red | English fallback | This call has shown serious warning signs. Do not send money or share banking details now. End the call and ask someone you trust for help. | `assets/warnings/red-en.wav` |

## Review and source

- Drafted for this handoff on 1 October 2026. **No fluent speaker has yet approved the Hindi or Telugu wording or pronunciation.** Do not label these clips as native-reviewed or use them in a final demonstration until a fluent reviewer listens to each clip and records their name, date, decision, and corrections here.
- Hindi reviewer: pending. Telugu reviewer: pending. English review: pending.
- Audio source: eSpeak NG 1.52.0, official Windows release, extracted to a temporary folder; offline voices `hi`, `te`, and `en`. These clips are synthesized from the exact text above, without a cloud TTS service. Source call audio and user recordings are not part of these assets.
- All six files were generated on 1 October 2026. Python's WAV reader decoded each as mono, 22,050 Hz, 16-bit PCM with nonzero audio samples. Windows `System.Media.SoundPlayer.PlaySync()` completed for every file without an error. This verifies local file playback; it does **not** establish that the Hindi or Telugu pronunciation is intelligible. Browser and phone playback remain pending Cyril's integration and device check.

## Reviewer record

| Language | Reviewer and date | Wording decision | Clip pronunciation decision | Corrections |
| --- | --- | --- | --- | --- |
| Hindi | Pending | Pending | Pending | Pending |
| Telugu | Pending | Pending | Pending | Pending |
| English | Pending | Pending | Pending | Pending |
