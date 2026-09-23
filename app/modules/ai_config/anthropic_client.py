"""One shared server-side Anthropic call site (Phase 5 follow-up §6) —
extracted so AI Search, hosted triage, and lightweight fit assessment don't
each carry their own copy of key decryption + HTTP setup + status-code
mapping + text extraction. Anthropic-only, deliberately: no provider
abstraction/framework, since only one provider is supported today (see
app.modules.ai_config.service.ANTHROPIC_MODELS).
"""

from dataclasses import dataclass, field

import httpx

from app.core.config import Settings
from app.modules.ai_config import service as ai_config_service
from app.modules.ai_config.models import CandidateAIConfig

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class AnthropicCallResult:
    status: str  # "ok" | "unauthorized" | "rate_limited" | "error"
    text: str = ""
    error: str | None = None
    raw: dict = field(default_factory=dict)


async def call_anthropic(settings: Settings, config: CandidateAIConfig, *, messages: list[dict], max_tokens: int = 800, tools: list[dict] | None = None, timeout: float = 45) -> AnthropicCallResult:
    """Server-side only — decrypts `config`'s key for exactly this one
    outbound call and never returns it. Callers distinguish `unauthorized`/
    `rate_limited` from a generic `error` because they usually want
    different behavior (e.g. stop processing this candidate's queue on a
    bad key, but just skip one item on a transient network error)."""
    api_key = ai_config_service.decrypt_api_key(settings, config)
    payload: dict = {"model": config.model, "max_tokens": max_tokens, "messages": messages}
    if tools:
        payload["tools"] = tools
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(ANTHROPIC_API_URL, json=payload, headers=headers)
    except httpx.HTTPError as error:
        return AnthropicCallResult(status="error", error=f"AI provider request failed: {error}")

    if response.status_code == 401:
        return AnthropicCallResult(status="unauthorized", error="AI provider rejected the configured API key")
    if response.status_code == 429:
        return AnthropicCallResult(status="rate_limited", error="AI provider rate-limited this request — try again shortly")
    if response.status_code != 200:
        return AnthropicCallResult(status="error", error=f"AI provider returned HTTP {response.status_code}")

    body = response.json()
    text = "".join(block.get("text", "") for block in body.get("content", []) if isinstance(block, dict) and block.get("type") == "text")
    return AnthropicCallResult(status="ok", text=text, raw=body)
