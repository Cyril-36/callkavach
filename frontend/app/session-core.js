// Pure session logic for the listener app: the /ws/audio protocol, the state reducer and the
// reading of the relay's Stop result. No DOM, no audio, so it runs under `node --test`.
// The protocol is documented in backend/spike/audio_ws.py and backend/spike/DETECTOR_CONTRACT.md.

// Only the languages the relay accepts (audio_ws.LANGUAGES). `code` names the warning clip folder.
export const LANGS = [
  { code: "hi", stt: "hi-IN", name: "Hindi", label: "हिन्दी — Hindi" },
  { code: "te", stt: "te-IN", name: "Telugu", label: "తెలుగు — Telugu" },
  { code: "en", stt: "en-IN", name: "English", label: "English" },
];

// The relay's Stop deadline is 6 s (FINALIZE_DEADLINE_S) plus a 1 s provider close; wait a little longer.
export const STOP_WAIT_MS = 8000;
// Silence streamed after Stop (microphone already released) so the last utterance is finalized by the
// transcriber's own end-of-speech detection rather than by the Stop flush. In the PR #12 runs, Stop after
// 1.5 s of silence was never cut off (0 of 4); Stop straight after speech was cut off in 4 of 12.
export const STOP_TAIL_SILENCE_S = 1.5;
// After that tail, keep sending silence (never microphone audio) while a sentence is still being
// transcribed or the last segments are still being checked, up to this long, and only then send stop.
// The relay's own 6 s Stop deadline is unchanged; this only decides when the client asks to stop.
export const STOP_DRAIN_MAX_S = 12;
export const SAMPLE_RATE = 16000;

export const TACTICS = {
  claimed_authority: "Claims to be from an authority — police, bank, court, courier or similar",
  threat_or_fabricated_crime: "A threat or accusation — arrest, a case, a blocked account or seized parcel",
  secrecy_or_isolation: "Asks you to keep it secret, stay on the call or not tell anyone",
  urgency_pressure: "Pressure to act right now",
  credential_request: "Asks for an OTP, PIN, password or card details",
  remote_access_request: "Asks you to install an app or share your screen",
  money_transfer_request: "Asks you to pay or transfer money",
  personal_id_request: "Asks for Aadhaar, PAN or other ID numbers",
};
// Spoken warning text, verbatim from docs/warning-copy.md (reviewed Hindi and Telugu wording, English
// fallback). Generic by design: the evidence quotes supply the specific reason. Keyed "{level}-{lang}".
export const WARNING_COPY = {
  "amber-hi": "इस कॉल में कुछ चिंताजनक संकेत मिले हैं। पैसे या जानकारी देने से पहले, कॉल रोकें। आधिकारिक नंबर पर कॉल करके जाँच करें।",
  "red-hi": "इस कॉल में गंभीर जोखिम के संकेत मिले हैं। अभी पैसे या बैंक की जानकारी साझा न करें। कॉल काटें। किसी भरोसेमंद व्यक्ति से मदद लें।",
  "amber-te": "ఈ కాల్\u200cలో కొన్ని ఆందోళనకరమైన సూచనలు కనిపించాయి. డబ్బు లేదా సమాచారం ఇచ్చే ముందు, కాల్ ఆపండి. అధికారిక నంబర్\u200cకు ఫోన్ చేసి నిర్ధారించుకోండి.",
  "red-te": "ఈ కాల్\u200cలో తీవ్రమైన ప్రమాద సూచనలు కనిపించాయి. ఇప్పుడు డబ్బు లేదా బ్యాంకు వివరాలు పంచుకోవద్దు. కాల్ ముగించండి. నమ్మకమైన వ్యక్తి సహాయం తీసుకోండి.",
  "amber-en": "This call has shown some warning signs. Pause before sending money or sharing information. Verify by calling an official number.",
  "red-en": "This call has shown serious warning signs. Do not send money or share banking details. End the call. Ask someone you trust for help.",
};

export const tacticLabel = (t) => TACTICS[t] || `Unrecognised tactic “${t}”`;

const LEVELS = ["none", "amber", "red"];

export function langByCode(code) {
  return LANGS.find((l) => l.code === code) || LANGS[0];
}

// The only two text messages the relay accepts. Anything else after start ends the session.
// access_code is sent only when set; a deployed relay with CALLKAVACH_ACCESS_CODE requires it.
export function startMessage(langCode, accessCode = "") {
  const m = { type: "start", encoding: "pcm_s16le", channels: 1, sample_rate: SAMPLE_RATE, language_code: langByCode(langCode).stt };
  return accessCode ? { ...m, access_code: accessCode } : m;
}
export const stopMessage = () => ({ type: "stop" });

export function freshSession(source, extra = {}) {
  return {
    source, // "live" | "sample" | "replay"
    phase: "idle",
    connection: "none",
    mic: source === "live" ? "off" : "unused",
    segs: [], // finalized transcript segments: {id, text, t}
    speaking: false,
    gaps: [], // {t, dur, source: "client" | "server" | "playback"}
    level: "none",
    reason: null,
    tactics: [], // [{tactic, label, evidence: [{segmentId, quote, t}]}]
    events: [], // level rises: {level, t, reason, tactics}
    analysis: "waiting", // waiting | ok | unavailable
    analysisError: null,
    analysed: 0,
    unanalysed: 0,
    calls: 0,
    lastLatency: null,
    cost: 0,
    audioT: 0,
    lastWordsAt: null,
    stopInfo: null,
    error: null,
    disconnectedAt: null,
    ...extra,
  };
}

// t is the client's audio clock (seconds of audio sent) when the message arrived.
export function reduce(s, m, t) {
  switch (m && m.type) {
    case "ready":
      return { ...s, phase: s.phase === "connecting" ? "listening" : s.phase, connection: "open" };
    case "speech":
      return { ...s, speaking: m.state === "started" };
    case "transcript": {
      if (!m.segment_id || s.segs.some((x) => x.id === m.segment_id)) return { ...s, speaking: false };
      const text = String(m.text || "").trim();
      if (!text) return { ...s, speaking: false };
      return { ...s, speaking: false, segs: [...s.segs, { id: m.segment_id, text, t }], lastWordsAt: t };
    }
    case "risk":
      return reduceRisk(s, m, t);
    case "gap":
      return { ...s, gaps: [...s.gaps, { t, dur: Number(m.duration_s) || 0, source: "server" }] };
    case "error":
      if (m.code === "access_denied") return { ...s, phase: "accessdenied", connection: "closed", error: m.message || "Access code missing or wrong." };
      if (m.code === "session_quota") return { ...s, phase: "quota", connection: "closed", error: m.message || "Session limit reached." };
      return { ...s, phase: "servererror", connection: "closed", error: m.message || m.code || "The server reported an error." };
    case "stopped": {
      const stopInfo = readStopped(m, s);
      // The final summary can only confirm or raise the level seen in risk events, never lower it.
      // An unreadable level stays unreadable: it is never replaced by the summary's "none".
      const level = s.level !== "unknown" && LEVELS.indexOf(stopInfo.level) > LEVELS.indexOf(s.level) ? stopInfo.level : s.level;
      return { ...s, phase: "stopped", connection: "closed", speaking: false, level, stopInfo };
    }
    default:
      return s;
  }
}

function reduceRisk(s, m, t) {
  const level = LEVELS.includes(m.level) ? m.level : "unknown";
  const segTime = Object.fromEntries(s.segs.map((x) => [x.id, x.t]));
  const tactics = (m.tactics || []).map((x) => ({
    tactic: x.tactic,
    label: tacticLabel(x.tactic),
    evidence: (x.evidence || []).map((q) => ({ segmentId: q.segment_id, quote: q.quote, t: segTime[q.segment_id] ?? null })),
  }));
  const next = {
    ...s,
    level,
    reason: m.reason ?? s.reason,
    tactics: tactics.length || m.analysis !== "unavailable" ? tactics : s.tactics,
    analysis: m.analysis === "unavailable" ? "unavailable" : "ok",
    analysisError: m.analysis === "unavailable" ? m.error || "analysis unavailable" : null,
    analysed: m.analysed_segments ?? s.analysed,
    unanalysed: m.unanalysed_segments ?? s.unanalysed,
    calls: m.calls ?? s.calls,
    lastLatency: m.latency_s ?? s.lastLatency,
    cost: s.cost + (m.verifier && typeof m.verifier.cost === "number" ? m.verifier.cost : 0),
    newEvent: null,
  };
  const prev = s.events.length ? s.events[s.events.length - 1].level : "none";
  if (LEVELS.indexOf(level) > LEVELS.indexOf(prev)) {
    const ev = { level, t, reason: m.reason || null, tactics: tactics.map((x) => x.tactic) };
    next.events = [...s.events, ev];
    next.newEvent = ev;
  }
  return next;
}

// Whether Stop should keep streaming silence before sending stop: a sentence is still open, or segments
// already transcribed have not been checked yet and analysis has not failed.
export function needsDrain(s) {
  return !!(s.speaking || (s.analysis !== "unavailable" && s.segs.length > s.analysed));
}

// What the relay's `stopped` message says about completeness. Nothing is "fully analysed" unless the
// transcription is complete, analysis is complete and no audio was dropped on either side.
export function readStopped(m, s = {}) {
  const a = m.analysis || {};
  const serverDropped = Number(m.dropped_s) || 0;
  const clientDropped = (s.gaps || []).filter((g) => g.source === "client").reduce((n, g) => n + g.dur, 0);
  const problems = [];
  if (m.transcription !== "complete") problems.push({ tag: "TRANSCRIPT", text: `Transcription incomplete: ${m.reason || "no reason given"}.` });
  if (a.cut_off_by_stop_deadline) {
    const parts = [];
    if (a.in_flight_segments || a.in_flight_for_s != null) parts.push(`a check covering ${a.in_flight_segments} segment(s) was cancelled after ${Number(a.in_flight_for_s || 0).toFixed(1)} s`);
    if (a.queued_segments) parts.push(`${a.queued_segments} segment(s) were never checked`);
    problems.push({ tag: "CUT OFF", text: `Stop deadline reached before analysis finished: ${parts.join(" and ") || "analysis was still running"}.` });
  } else if (a.status === "incomplete") {
    problems.push({ tag: "ANALYSIS", text: `Analysis incomplete${a.unanalysed_segments ? `: ${a.unanalysed_segments} segment(s) not checked` : ""}${a.error ? ` (${a.error})` : ""}.` });
  } else if (a.status === "unavailable") {
    problems.push({ tag: "ANALYSIS", text: `Scam-tactic analysis was unavailable${a.error ? `: ${a.error}` : ""}.` });
  } else if (a.status !== "complete") {
    problems.push({ tag: "ANALYSIS", text: `Analysis status “${a.status ?? "missing"}” — not confirmed complete.` });
  }
  if (serverDropped > 0) problems.push({ tag: "GAP", text: `${serverDropped.toFixed(1)} s of audio was dropped by the server and never transcribed.` });
  if (clientDropped > 0) problems.push({ tag: "GAP", text: `${clientDropped.toFixed(1)} s of audio was never sent (connection too slow).` });
  const muted = (s.gaps || []).filter((g) => g.source === "playback").reduce((n, g) => n + g.dur, 0);
  if (muted > 0) problems.push({ tag: "MUTED", text: `${muted.toFixed(1)} s was muted while warnings played, so anything said then was not checked.` });
  return {
    confirmed: true,
    complete: problems.length === 0,
    transcription: m.transcription || null,
    analysisStatus: a.status || null,
    cutOff: !!a.cut_off_by_stop_deadline,
    level: a.level ?? null,
    segments: m.segments ?? null,
    durationS: m.duration_s ?? null,
    problems,
  };
}

// No `stopped` arrived (timeout or the socket closed first): nothing can be called complete.
export function unconfirmedStop(why) {
  return { confirmed: false, complete: false, transcription: null, analysisStatus: null, cutOff: false, level: null, problems: [{ tag: "STOP", text: `The server did not confirm the end of analysis (${why}). Treat the last part as unchecked.` }] };
}

// Headline and body for the main warning card. The level always comes from the backend.
export function headlineFor(s) {
  const cur = s.level === "amber" || s.level === "red" ? s.level : null;
  if (s.phase === "stopped" && s.stopInfo) {
    const si = s.stopInfo;
    if (si.early) return { tone: "neutral", headline: "Stopped before listening started", body: "Nothing was heard or checked." };
    if (cur) return { tone: cur, headline: cur === "red" ? "Stopped · red warning was raised" : "Stopped · amber warning was raised", body: si.complete ? "Everything heard was checked." : "Part of the audio was NOT checked — see below." };
    if (!si.complete) return { tone: "failure", headline: "Stopped · analysis INCOMPLETE — no conclusion", body: "Some of what was said was not transcribed or not checked, so “no warning” here means nothing. See the reasons below." };
    return { tone: "neutral", headline: s.source === "sample" ? "Sample fully analysed · no warning raised" : "Stopped · no warning was raised", body: "Everything heard was transcribed and checked. No warning does not mean the call was safe." };
  }
  if (cur) return { tone: cur, headline: cur === "red" ? "Stop. Don’t share anything or pay." : "Be careful", body: s.tactics.map((x) => x.label).join(". ") + "." };
  if (s.level === "unknown") return { tone: "failure", headline: "Warning level unreadable", body: "The backend sent a warning level this app doesn’t recognise. Treat the call with caution." };
  if (s.phase === "listening" && s.analysis === "unavailable") return { tone: "failure", headline: "Listening, but analysis is unavailable", body: `Words are being transcribed but NOT checked for scam tactics (${s.analysisError}). Treat the call with caution.` };
  return null;
}
