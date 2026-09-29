"""Chooses the tactic verifier from server-side configuration. Exactly one provider; no fallback.

LLM_PROVIDER=aicredits (default, primary): AICREDITS_API_KEY, AICREDITS_MODEL, optional AICREDITS_BASE_URL.
LLM_PROVIDER=gemini (direct Google): GEMINI_API_KEY, GEMINI_MODEL.
LLM_PROVIDER=off: no analysis (reported to the browser as unavailable), for tests that must not make paid calls.
Values come from the environment or the repo's .env. If the selected provider is not fully configured,
analysis is reported unavailable; the other provider is never tried instead.
"""
import os
from pathlib import Path

from aicredits_verifier import DEFAULT_BASE_URL, AICreditsVerifier
from gemini_verifier import GeminiVerifier


def _config(name: str):
    if os.environ.get(name):
        return os.environ[name]
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return None


def make_verifier():
    """Returns (verifier, None) or (None, reason it is unavailable)."""
    provider = (_config("LLM_PROVIDER") or "aicredits").strip().lower()
    if provider == "aicredits":
        key, model = _config("AICREDITS_API_KEY"), _config("AICREDITS_MODEL")
        if not key or not model:
            missing = "AICREDITS_API_KEY" if not key else "AICREDITS_MODEL"
            return None, f"{missing} is not configured on the server (LLM_PROVIDER=aicredits)"
        return AICreditsVerifier(key, model, base_url=_config("AICREDITS_BASE_URL") or DEFAULT_BASE_URL), None
    if provider == "gemini":
        key, model = _config("GEMINI_API_KEY"), _config("GEMINI_MODEL")
        if not key or not model:
            missing = "GEMINI_API_KEY" if not key else "GEMINI_MODEL"
            return None, f"{missing} is not configured on the server (LLM_PROVIDER=gemini)"
        return GeminiVerifier(key, model), None
    if provider == "off":  # e.g. browser lifecycle tests: reported as unavailable, never silently skipped
        return None, "scam analysis is switched off on this server (LLM_PROVIDER=off)"
    return None, f"LLM_PROVIDER={provider!r} is not supported (use aicredits, gemini or off)"
