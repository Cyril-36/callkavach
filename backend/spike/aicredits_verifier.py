"""AICredits gateway tactic verifier (OpenAI-compatible chat completions). CallKavach's primary provider.

Documented API (aicredits.in/docs/api-reference, checked 2026-09-29): POST {base}/v1/chat/completions
with "Authorization: Bearer <key>"; response_format supports {"type": "json_object"} (no JSON schema);
responses carry model, choices[].message.content, finish_reason and usage (with cost). The public model
catalog is GET {base}/api/models.

The configured model must be the one that answers: if the gateway reports a different model, the reply
is rejected rather than silently accepted. There is no fallback to another provider or model.
"""
import json

import httpx

from detector import VerifierError
from gemini_verifier import SYSTEM_PROMPT

DEFAULT_BASE_URL = "https://api.aicredits.in"


class AICreditsVerifier:
    provider = "aicredits"

    def __init__(self, api_key: str, model: str, *, base_url: str = DEFAULT_BASE_URL, timeout_s: float = 8.0,
                 client: httpx.AsyncClient | None = None, max_tokens: int = 4096):
        # max_tokens is generous because Gemini 2.5 Flash spends output tokens on internal reasoning first:
        # a 20-token cap returned finish_reason "length" with no content at all.
        self.api_key, self.model, self.max_tokens = api_key, model, max_tokens
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.client = client or httpx.AsyncClient(timeout=timeout_s)
        self.last_call = None

    def body(self, request: dict) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

    async def analyse(self, request: dict) -> list:
        self.last_call = None  # never report a previous call's model or cost for this one
        try:
            r = await self.client.post(self.url, json=self.body(request),
                                       headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            raise VerifierError(f"AICredits request failed ({type(e).__name__})") from e
        if r.status_code != 200:
            try:
                detail = str((r.json().get("error") or {}).get("message", ""))[:200]
            except ValueError:
                detail = r.text[:200]
            raise VerifierError(f"AICredits HTTP {r.status_code}: {detail}")
        try:
            data = r.json()
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            self.last_call = {"provider": self.provider, "requested_model": self.model,
                              "returned_model": data.get("model"), "finish_reason": choice.get("finish_reason"),
                              "prompt_tokens": usage.get("prompt_tokens"),
                              "completion_tokens": usage.get("completion_tokens"),
                              "cost": usage.get("cost"), "gateway_latency_ms": usage.get("latency_ms")}
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise VerifierError(f"AICredits reply unusable ({type(e).__name__})") from e
        if data.get("model") != self.model:
            raise VerifierError(f"gateway answered with model {data.get('model')!r}, not the configured {self.model!r}")
        if choice.get("finish_reason") != "stop":
            raise VerifierError(f"AICredits stopped early: {choice.get('finish_reason')}")
        try:
            content = choice["message"]["content"]
            findings = json.loads(content)["findings"]
        except (ValueError, KeyError, TypeError) as e:
            raise VerifierError(f"AICredits reply is not the findings JSON object ({type(e).__name__})") from e
        return findings  # SessionDetector validates every finding strictly

    async def close(self) -> None:
        await self.client.aclose()
