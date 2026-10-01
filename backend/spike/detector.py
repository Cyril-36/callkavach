"""Incremental scam-tactic detector: input contract, bounded session state and deterministic risk.

Contract
  Input: finalized transcript segments in arrival order, as `Segment(segment_id, text, received_ms)`.
  Nothing else crosses into the detector: no speaker labels (live STT has none), no family IDs, labels,
  first-ask times or future dialogue. `Segment.from_event` reads only those three fields.
  Output: `risk` events (see `SessionDetector._risk_event`), emitted after each analysis or failure.
  Events are built by the sender at its send boundary (`send(build)` calls `build(now_ms)` after taking its
  WebSocket send lock), so `emitted_at_ms`, `first_warning_at_ms`, `first_red_at_ms` and `summary()` all use
  the time the event actually went out.

Design
  - A verifier (Gemini, or a mock in tests) labels tactics in a bounded window of recent segments. There is
    no keyword gate in front of it: Sarvam transliterates and mishears acronyms (OTP, ओटीपी, KYC, "Cibir"),
    so every finalized segment is analysed, subject to the call bounds below.
  - The verifier must quote its evidence. A finding counts only if its quote occurs in the named segment
    of the window it was shown, so a hallucinated or relocated quote is dropped.
  - Risk is computed here, deterministically, from confirmed tactics. The model never sets the level.
  - Bounded cost: one call in flight, segments that arrive meanwhile are coalesced into the next call,
    a minimum interval between calls, a per-call timeout, and a per-session call budget.
  - Bounded context: the last `window_segments` segments within `window_chars`, plus up to
    `max_quotes_per_tactic` retained quotes per confirmed tactic, so a slow scam keeps its early clues.
  - Failures are visible: a failed or skipped analysis emits `analysis: "unavailable"` with the reason and
    keeps the current level. The detector never reports a call as safe; "none" means no warning yet.
"""
import asyncio
import re
import unicodedata
import time
from collections import deque
from dataclasses import dataclass

TACTICS = (
    "claimed_authority",  # claims to be police, CBI, court, regulator, bank, courier, utility, etc.
    "threat_or_fabricated_crime",  # arrest, case, seized parcel, account freeze, disconnection threats
    "secrecy_or_isolation",  # tell no one, stay on the call, do not contact family/bank/provider
    "urgency_pressure",  # act now, within the hour, before it is too late
    "credential_request",  # asks the listener to reveal OTP, PIN, password, CVV, card or bank details
    "remote_access_request",  # asks to install an app, share screen or give remote control
    "money_transfer_request",  # asks to pay, transfer, move savings, send via UPI or to an account
    "personal_id_request",  # asks for Aadhaar, PAN or other identity numbers
)
_PRESSURE = {"claimed_authority", "threat_or_fabricated_crime", "secrecy_or_isolation", "urgency_pressure",
             "money_transfer_request", "personal_id_request"}
_COERCION = {"claimed_authority", "threat_or_fabricated_crime", "secrecy_or_isolation"}
LEVELS = ("none", "amber", "red")
STATUSES = ("present", "negated", "benign")
_FINDING_KEYS = {"tactic", "status", "segment_id", "quote"}
_OPTIONAL_KEYS = {"reason"}
MAX_QUOTE_CHARS = 300

# Four or more digits, optionally separated by single spaces or hyphens ("4821", "4 8 2 1", "1234-5678").
# \d matches Unicode digits, so Devanagari and Telugu numerals are masked too. Spelled-out numbers are not.
_NUMBER = re.compile(r"\d(?:[ -]?\d){3,}")


def redact(text: str) -> str:
    return _NUMBER.sub("[NUMBER]", text)


_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))  # soft hyphen, zero-width chars


def _norm(text: str) -> str:
    """Comparison form for quote checks, applied identically to the quote and its segment.

    Unicode NFKC (Telugu and Devanagari vowel signs can be composed or decomposed), invisible joiners
    removed, every punctuation character (danda, curly quotes, ellipsis, brackets...) turned into a
    space, case folded and whitespace collapsed. The words themselves must still match in order.
    """
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE)
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class Segment:
    segment_id: str
    text: str
    received_ms: int

    @classmethod
    def from_event(cls, event: dict, received_ms: int) -> "Segment":
        """Build detector input from a transcript event, reading only the permitted fields."""
        return cls(segment_id=str(event["segment_id"]), text=str(event["text"]), received_ms=received_ms)


def risk_level(tactics: set) -> tuple:
    """Deterministic warning policy (initial heuristics from the build plan, to be tuned on dev data only)."""
    if "credential_request" in tactics or "remote_access_request" in tactics:
        return "red", "request for credentials or remote access"
    if "money_transfer_request" in tactics and tactics & _COERCION:
        return "red", "money request with claimed authority, threat or secrecy"
    if _COERCION <= tactics:
        return "red", "claimed authority, threat and secrecy together"
    if len(tactics & _PRESSURE) >= 2:
        return "amber", "two or more pressure tactics"
    return "none", None


class VerifierError(Exception):
    pass


@dataclass
class _Quote:
    segment_id: str
    quote: str


class SessionDetector:
    """One per call session. `add()` finalized segments in order; results arrive through `emit`."""

    def __init__(self, verifier, emit=None, *, send=None, max_calls=60, min_interval_s=1.0, call_timeout_s=8.0,
                 window_segments=12, window_chars=4000, max_quotes_per_tactic=3, max_pending=50, clock=None):
        """emit(event): simple sink, stamped with `clock` just before the call (tests, smoke scripts).
        send(build): sender-controlled stamping; it must call build(now_ms) at its real send boundary
        (the relay does this after acquiring its WebSocket send lock). Exactly one of the two is used."""
        self.verifier = verifier
        loop = asyncio.get_running_loop()
        created = loop.time()
        # Milliseconds since the session started, on the server's monotonic clock.
        self.clock = clock or (lambda: int((loop.time() - created) * 1000))
        if send is None:
            async def send(build):
                await emit(build(self.clock()))
        self.send = send
        self.max_calls, self.min_interval_s, self.call_timeout_s = max_calls, min_interval_s, call_timeout_s
        self.window_segments, self.window_chars = window_segments, window_chars
        self.max_quotes_per_tactic, self.max_pending = max_quotes_per_tactic, max_pending
        # (alias, segment_id, redacted text, received_ms), oldest first. The verifier sees only the short alias
        # ("seg1", "seg2", ...): provider segment IDs are long and a model mis-copied one in a live test.
        self.window = deque()
        self._next_alias = 1
        self.pending = deque()
        self.evidence = {}  # tactic -> [_Quote]
        self.level, self.level_reason = "none", None
        self.calls = self.analysed = self.rejected_findings = 0
        self.first_warning_at_ms = self.first_red_at_ms = None  # emission times of the first amber/red
        self.analysed_through_ms = None  # receive time of the newest segment covered by a successful analysis
        self.last_call_rejected = 0
        self.done_ids = set()  # window segments included in a successful analysis
        self.lost = 0  # segments that left the window, or overflowed the queue, without being analysed
        self.last_error = None
        self.analysis = "ok"
        self.in_flight = False
        self._call_started_at = None  # loop time of the call in flight, for cut-off reporting
        self._in_flight_ids = set()  # segments not yet analysed that the call in flight covers
        self._wake = asyncio.Event()
        self._last_call_at = None
        self._task = asyncio.get_running_loop().create_task(self._run())

    # --- input ---
    def add(self, segment: Segment) -> None:
        if len(self.pending) >= self.max_pending:  # never unbounded; a dropped segment is reported
            self.pending.popleft()
            self.lost += 1
        self.pending.append(segment)
        self._wake.set()

    def idle(self) -> bool:
        return not self.pending and not self.in_flight

    async def close(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

    # --- worker ---
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await self._wake.wait()
            self._wake.clear()
            if not self.pending:
                continue
            if self._last_call_at is not None:
                wait = self.min_interval_s - (loop.time() - self._last_call_at)
                if wait > 0:
                    await asyncio.sleep(wait)  # more segments may arrive and be coalesced meanwhile
            new = list(self.pending)
            self.pending.clear()
            for seg in new:
                self._push_window(seg)
            if self.calls >= self.max_calls:
                await self._fail(f"analysis call budget of {self.max_calls} exhausted")
                continue
            self.in_flight = True
            self.calls += 1
            self._last_call_at = self._call_started_at = loop.time()
            started = time.perf_counter()
            request_ids = {sid for _, sid, _, _ in self.window}
            # Segments not yet covered by a successful analysis (new ones, and earlier failures still in the
            # window) are marked new, so a retry asks the model to look at them again.
            unanalysed_ids = request_ids - self.done_ids
            self._in_flight_ids = set(unanalysed_ids)
            self.last_call_rejected = 0
            try:
                findings = await asyncio.wait_for(self.verifier.analyse(self._request(unanalysed_ids)),
                                                  self.call_timeout_s)
                accepted, rejected = self._validate(findings)  # raises if the reply is not a findings list
            except asyncio.TimeoutError:
                await self._fail(f"analysis timed out after {self.call_timeout_s:g} s")
            except Exception as e:  # VerifierError, transport errors, malformed replies
                await self._fail(f"analysis failed: {e}")
            else:
                if rejected:
                    # Any finding that fails schema, alias or quote checks makes the whole response a failed
                    # analysis: none of it is applied, its segments stay unanalysed for a retry, and the
                    # current warning is kept.
                    self.last_call_rejected = len(rejected)
                    self.rejected_findings += len(rejected)
                    await self._fail(f"analysis failed: {len(rejected)} finding(s) rejected: " + "; ".join(rejected[:3]))
                else:
                    self.analysed += len(unanalysed_ids)
                    self.done_ids |= request_ids
                    self.analysed_through_ms = max(ms for _, _, _, ms in self.window)
                    self._apply(accepted)
                    self.analysis, self.last_error = "ok", None
                    latency_s = time.perf_counter() - started
                    await self.send(lambda now: self._risk_event(now, latency_s=latency_s))
            finally:
                self.in_flight = False
                self._call_started_at = None
                self._in_flight_ids = set()
            if self.pending:
                self._wake.set()

    def _push_window(self, seg: Segment) -> None:
        self.window.append((f"seg{self._next_alias}", seg.segment_id, redact(seg.text), seg.received_ms))
        self._next_alias += 1
        while len(self.window) > self.window_segments or (
                len(self.window) > 1 and sum(len(t) for _, _, t, _ in self.window) > self.window_chars):
            _, sid, _, _ = self.window.popleft()
            if sid in self.done_ids:
                self.done_ids.discard(sid)
            else:
                self.lost += 1

    def _request(self, new_ids: set) -> dict:
        """The only data the verifier sees: redacted recent segments and previously confirmed evidence."""
        return {
            "confirmed_evidence": [{"tactic": t, "quote": q.quote} for t, qs in self.evidence.items() for q in qs],
            "segments": [{"segment_id": alias, "text": text, "new": sid in new_ids}
                         for alias, sid, text, _ in self.window],
        }

    def _validate(self, findings) -> tuple:
        """Strictly check every finding. Returns (accepted present findings, rejection reasons).

        A reply that is not a list of objects is a failed analysis. Each finding needs exactly the
        fields tactic, status, segment_id and quote (reason optional), all strings; a known tactic and
        status; a segment from this request; and a non-empty quote of at most MAX_QUOTE_CHARS that occurs
        in that segment. Negated and benign findings are validated too, but only present ones are evidence.
        """
        if not isinstance(findings, list):
            raise VerifierError("reply is not a list of findings")
        window = {alias: (sid, _norm(text)) for alias, sid, text, _ in self.window}
        accepted, rejected = [], []
        for i, f in enumerate(findings):
            if not isinstance(f, dict):
                rejected.append(f"#{i} is not an object")
                continue
            keys = set(f)
            if not _FINDING_KEYS <= keys or keys - _FINDING_KEYS - _OPTIONAL_KEYS:
                rejected.append(f"#{i} has fields {sorted(keys)}")
                continue
            if not all(isinstance(f[k], str) for k in keys):
                rejected.append(f"#{i} has a non-string field")
                continue
            tactic, status, sid, quote = f["tactic"], f["status"], f["segment_id"], f["quote"].strip()
            if tactic not in TACTICS:
                rejected.append(f"#{i} unknown tactic {tactic[:40]!r}")
            elif status not in STATUSES:
                rejected.append(f"#{i} unknown status {status[:40]!r}")
            elif sid not in window:
                rejected.append(f"#{i} segment {sid[:40]!r} not in this request")
            elif not _norm(quote) or len(quote) > MAX_QUOTE_CHARS:
                rejected.append(f"#{i} empty or over-long quote")
            elif _norm(quote) not in window[sid][1]:
                rejected.append(f"#{i} quote not found in {sid[:40]}")
            elif status == "present":  # map the alias back to the real segment ID
                accepted.append({"tactic": tactic, "segment_id": window[sid][0], "quote": quote})
        return accepted, rejected

    def _apply(self, accepted: list) -> None:
        for f in accepted:
            quotes = self.evidence.setdefault(f["tactic"], [])
            if any(q.segment_id == f["segment_id"] and _norm(q.quote) == _norm(f["quote"]) for q in quotes):
                continue
            if len(quotes) < self.max_quotes_per_tactic:
                quotes.append(_Quote(f["segment_id"], f["quote"]))
        level, reason = risk_level(set(self.evidence))
        if LEVELS.index(level) > LEVELS.index(self.level):  # warnings are never silently cleared
            self.level, self.level_reason = level, reason

    async def _fail(self, message: str) -> None:
        self.analysis, self.last_error = "unavailable", message
        await self.send(lambda now: self._risk_event(now))

    def unanalysed(self) -> int:
        return self.lost + len({sid for _, sid, _, _ in self.window} - self.done_ids) + len(self.pending)

    def _risk_event(self, now: int, latency_s=None) -> dict:
        """Built by the sender at its send boundary with the emission time `now` (session milliseconds)."""
        if self.level in ("amber", "red") and self.first_warning_at_ms is None:
            self.first_warning_at_ms = now
        if self.level == "red" and self.first_red_at_ms is None:
            self.first_red_at_ms = now
        return {
            "type": "risk",
            "emitted_at_ms": now,
            "first_warning_at_ms": self.first_warning_at_ms,
            "first_red_at_ms": self.first_red_at_ms,
            "analysed_through_ms": self.analysed_through_ms,
            "level": self.level,  # "none" means no warning yet, never "safe"
            "reason": self.level_reason,
            "analysis": self.analysis,
            "error": self.last_error,
            "tactics": [{"tactic": t, "evidence": [{"segment_id": q.segment_id, "quote": q.quote} for q in qs]}
                        for t, qs in self.evidence.items()],
            "analysed_segments": self.analysed,
            "unanalysed_segments": self.unanalysed(),
            "calls": self.calls,
            "rejected_findings": self.last_call_rejected,
            "latency_s": None if latency_s is None else round(latency_s, 3),
            "verifier": getattr(self.verifier, "last_call", None),
        }

    def summary(self) -> dict:
        """State for the session's final report."""
        if not self.idle():
            status = "pending"
        elif self.analysis != "ok" or self.unanalysed():
            status = "incomplete"
        else:
            status = "complete"
        return {"level": self.level, "reason": self.level_reason, "status": status, "error": self.last_error,
                "analysed_segments": self.analysed, "unanalysed_segments": self.unanalysed(),
                "calls": self.calls, "tactics": sorted(self.evidence), "rejected_findings": self.rejected_findings,
                "in_flight_for_s": None if self._call_started_at is None else
                round(asyncio.get_running_loop().time() - self._call_started_at, 3),
                # Not yet analysed: covered by the call in flight, vs queued and never sent to the model.
                "in_flight_segments": len(self._in_flight_ids) if self.in_flight else 0,
                "queued_segments": len(self.pending),
                "first_warning_at_ms": self.first_warning_at_ms, "first_red_at_ms": self.first_red_at_ms}
