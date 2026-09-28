"""Incremental scam-tactic detector: input contract, bounded session state and deterministic risk.

Contract
  Input: finalized transcript segments in arrival order, as `Segment(segment_id, text, received_ms)`.
  Nothing else crosses into the detector: no speaker labels (live STT has none), no family IDs, labels,
  first-ask times or future dialogue. `Segment.from_event` reads only those three fields.
  Output: `risk` events (see `SessionDetector._risk_event`), emitted after each analysis or failure.

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

# Four or more digits, optionally separated by single spaces or hyphens ("4821", "4 8 2 1", "1234-5678").
# \d matches Unicode digits, so Devanagari and Telugu numerals are masked too. Spelled-out numbers are not.
_NUMBER = re.compile(r"\d(?:[ -]?\d){3,}")


def redact(text: str) -> str:
    return _NUMBER.sub("[NUMBER]", text)


def _norm(text: str) -> str:
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

    def __init__(self, verifier, emit, *, max_calls=60, min_interval_s=1.0, call_timeout_s=8.0,
                 window_segments=12, window_chars=4000, max_quotes_per_tactic=3, max_pending=50):
        self.verifier, self.emit = verifier, emit
        self.max_calls, self.min_interval_s, self.call_timeout_s = max_calls, min_interval_s, call_timeout_s
        self.window_segments, self.window_chars = window_segments, window_chars
        self.max_quotes_per_tactic, self.max_pending = max_quotes_per_tactic, max_pending
        self.window = deque()  # (segment_id, redacted text), oldest first
        self.pending = deque()
        self.evidence = {}  # tactic -> [_Quote]
        self.level, self.level_reason = "none", None
        self.calls = self.analysed = self.rejected_findings = 0
        self.done_ids = set()  # window segments included in a successful analysis
        self.lost = 0  # segments that left the window, or overflowed the queue, without being analysed
        self.last_error = None
        self.analysis = "ok"
        self.in_flight = False
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
            self._last_call_at = loop.time()
            started = time.perf_counter()
            request_ids = {sid for sid, _ in self.window}
            try:
                findings = await asyncio.wait_for(self.verifier.analyse(self._request({s.segment_id for s in new})),
                                                  self.call_timeout_s)
            except asyncio.TimeoutError:
                await self._fail(f"analysis timed out after {self.call_timeout_s:g} s")
            except Exception as e:  # VerifierError, transport errors, malformed replies
                await self._fail(f"analysis failed: {e}")
            else:
                self.analysed += len(request_ids - self.done_ids)
                self.done_ids |= request_ids  # a retry covers earlier failed segments still in the window
                self._apply(findings)
                self.analysis, self.last_error = "ok", None
                await self.emit(self._risk_event(latency_s=time.perf_counter() - started))
            finally:
                self.in_flight = False
            if self.pending:
                self._wake.set()

    def _push_window(self, seg: Segment) -> None:
        self.window.append((seg.segment_id, redact(seg.text)))
        while len(self.window) > self.window_segments or (
                len(self.window) > 1 and sum(len(t) for _, t in self.window) > self.window_chars):
            sid, _ = self.window.popleft()
            if sid in self.done_ids:
                self.done_ids.discard(sid)
            else:
                self.lost += 1

    def _request(self, new_ids: set) -> dict:
        """The only data the verifier sees: redacted recent segments and previously confirmed evidence."""
        return {
            "confirmed_evidence": [{"tactic": t, "quote": q.quote} for t, qs in self.evidence.items() for q in qs],
            "segments": [{"segment_id": sid, "text": text, "new": sid in new_ids} for sid, text in self.window],
        }

    def _apply(self, findings) -> None:
        window = {sid: _norm(text) for sid, text in self.window}
        for f in findings if isinstance(findings, list) else []:
            tactic, status = f.get("tactic"), f.get("status")
            sid, quote = str(f.get("segment_id", "")), str(f.get("quote", "")).strip()
            if status != "present":
                continue  # negated, benign or reported speech: not evidence against the call
            if tactic not in TACTICS or sid not in window or not quote or len(quote) > 300 \
                    or _norm(quote) not in window[sid]:
                self.rejected_findings += 1  # unverifiable: unknown tactic, wrong segment, or quote not found
                continue
            quotes = self.evidence.setdefault(tactic, [])
            if any(q.segment_id == sid and _norm(q.quote) == _norm(quote) for q in quotes):
                continue
            if len(quotes) < self.max_quotes_per_tactic:
                quotes.append(_Quote(sid, quote))
        level, reason = risk_level(set(self.evidence))
        if LEVELS.index(level) > LEVELS.index(self.level):  # warnings are never silently cleared
            self.level, self.level_reason = level, reason

    async def _fail(self, message: str) -> None:
        self.analysis, self.last_error = "unavailable", message
        await self.emit(self._risk_event())

    def unanalysed(self) -> int:
        return self.lost + len({sid for sid, _ in self.window} - self.done_ids) + len(self.pending)

    def _risk_event(self, latency_s=None) -> dict:
        return {
            "type": "risk",
            "level": self.level,  # "none" means no warning yet, never "safe"
            "reason": self.level_reason,
            "analysis": self.analysis,
            "error": self.last_error,
            "tactics": [{"tactic": t, "evidence": [{"segment_id": q.segment_id, "quote": q.quote} for q in qs]}
                        for t, qs in self.evidence.items()],
            "analysed_segments": self.analysed,
            "unanalysed_segments": self.unanalysed(),
            "calls": self.calls,
            "latency_s": None if latency_s is None else round(latency_s, 3),
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
                "calls": self.calls, "tactics": sorted(self.evidence)}
