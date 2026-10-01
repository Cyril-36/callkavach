# Warning copy and offline clips

These are short, generic messages for an **amber** or **red** event. The event's on-screen evidence must supply the specific reason; these clips do not claim that a crime occurred or that the caller's identity is known. An analysis failure must be shown separately and must not play a reassuring message. Cyril owns playback and frontend integration.

| Level | Language | Spoken text | Clip |
| --- | --- | --- | --- |
| Amber | Hindi | इस कॉल में कुछ चिंताजनक संकेत मिले हैं। पैसे या जानकारी देने से पहले, कॉल रोकें। आधिकारिक नंबर पर कॉल करके जाँच करें। | `assets/warnings/amber-hi.wav` |
| Red | Hindi | इस कॉल में गंभीर जोखिम के संकेत मिले हैं। अभी पैसे या बैंक की जानकारी साझा न करें। कॉल काटें। किसी भरोसेमंद व्यक्ति से मदद लें। | `assets/warnings/red-hi.wav` |
| Amber | Telugu | ఈ కాల్‌లో కొన్ని ఆందోళనకరమైన సూచనలు కనిపించాయి. డబ్బు లేదా సమాచారం ఇచ్చే ముందు, కాల్ ఆపండి. అధికారిక నంబర్‌కు ఫోన్ చేసి నిర్ధారించుకోండి. | `assets/warnings/amber-te.wav` |
| Red | Telugu | ఈ కాల్‌లో తీవ్రమైన ప్రమాద సూచనలు కనిపించాయి. ఇప్పుడు డబ్బు లేదా బ్యాంకు వివరాలు పంచుకోవద్దు. కాల్ ముగించండి. నమ్మకమైన వ్యక్తి సహాయం తీసుకోండి. | `assets/warnings/red-te.wav` |
| Amber | English fallback | This call has shown some warning signs. Pause before sending money or sharing information. Verify by calling an official number. | `assets/warnings/amber-en.wav` |
| Red | English fallback | This call has shown serious warning signs. Do not send money or share banking details. End the call. Ask someone you trust for help. | `assets/warnings/red-en.wav` |

## Review and source

- Drafted and revised on 1 October 2026. Harshit reported that all six revised voices are clearer than the first eSpeak versions and approved the revised wording and pauses. He confirmed fluency in Hindi and Telugu and approved pronunciation in all four Hindi/Telugu clips. English pronunciation has not been separately confirmed.
- Audio source: offline Piper TTS 1.8.0 with the [`hi_IN-priyamvada-medium`](https://huggingface.co/rhasspy/piper-voices/tree/main/hi/hi_IN/priyamvada/medium), [`te_IN-padmavathi-medium`](https://huggingface.co/rhasspy/piper-voices/tree/main/te/te_IN/padmavathi/medium), and [`en_US-amy-medium`](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium) voices. The files were generated from the exact text above with `length-scale=1.1`, `noise-scale=0.72`, and `sentence-silence=0.35`. There was no cloud TTS call. Model files and source call audio are not in Git.
- The voice model cards list training-data terms: [Hindi CC BY-NC-SA 4.0](https://huggingface.co/rhasspy/piper-voices/blob/main/hi/hi_IN/priyamvada/medium/MODEL_CARD), [Telugu CC BY 4.0](https://huggingface.co/rhasspy/piper-voices/blob/main/te/te_IN/padmavathi/medium/MODEL_CARD), and an [English dataset reference](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/amy/medium/MODEL_CARD). Keep this provenance with any published use; this note does not settle rights to generated output.
- Python's WAV reader decoded each file as mono, 22,050 Hz, 16-bit PCM. Windows `System.Media.SoundPlayer.PlaySync()` completed for all six revised files. This verifies local file playback, not phone playback or pronunciation. Browser and phone playback remain pending Cyril's integration and device check.

## Reviewer record

| Language | Reviewer and date | Wording and pauses | Clip clarity | Pronunciation decision |
| --- | --- | --- | --- | --- |
| Hindi | Harshit-ambati, 1 October 2026; fluent speaker | Approved | Clearer than first version | Approved for both clips |
| Telugu | Harshit-ambati, 1 October 2026; fluent speaker | Approved | Clearer than first version | Approved for both clips |
| English | Harshit-ambati, 1 October 2026 | Approved | Clearer than first version | Pending explicit signoff |
