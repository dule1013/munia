"""Candidate-specific AI provider configuration (Phase 5 follow-up).

Munia has no shared/global AI credential — each candidate brings their own
Anthropic key, encrypted the same way Gmail OAuth tokens are (see
app/core/crypto.py). This module never returns a decrypted key to a route
handler except the one internal call site that needs it to make the actual
Anthropic API request (app.modules.discovery.ai_search).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.modules.ai_config.models import CandidateAIConfig

PROVIDER_ANTHROPIC = "anthropic"

# Small, explicit allowlist — never accept an arbitrary model string from a
# candidate. Verified against Anthropic's published pricing (platform.claude
# .com/docs/en/about-claude/pricing) at the time this was written; "cost_note"
# is informational for the Settings UI, not used in any billing logic.
ANTHROPIC_MODELS: dict[str, dict[str, str]] = {
    "claude-haiku-4-5-20251001": {"label": "Claude Haiku 4.5 (fast, inexpensive — default)", "cost_note": "$1 / $5 per million input/output tokens"},
    "claude-sonnet-5": {"label": "Claude Sonnet 5 (balanced)", "cost_note": "$3 / $15 per million input/output tokens"},
    "claude-opus-5": {"label": "Claude Opus 5 (highest quality, most expensive)", "cost_note": "$5 / $25 per million input/output tokens"},
}
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# Manual "AI Search" clicks are cheap per-call but not free — this is a
# floor against accidental rapid-fire clicking, not a real quota system.
MANUAL_SEARCH_COOLDOWN_SECONDS = 30


class UnsupportedModel(ValueError):
    pass


class UnsupportedProvider(ValueError):
    pass


def _aad(user_id: uuid.UUID, provider: str) -> str:
    return f"{user_id}:ai:{provider}"


async def get_ai_config(db: AsyncSession, user_id: uuid.UUID, provider: str = PROVIDER_ANTHROPIC) -> CandidateAIConfig | None:
    return await db.scalar(select(CandidateAIConfig).where(CandidateAIConfig.user_id == user_id, CandidateAIConfig.provider == provider))


async def set_api_key(db: AsyncSession, settings: Settings, *, user_id: uuid.UUID, provider: str, model: str, api_key: str) -> CandidateAIConfig:
    if provider != PROVIDER_ANTHROPIC:
        raise UnsupportedProvider(f"unsupported AI provider: {provider!r}")
    if model not in ANTHROPIC_MODELS:
        raise UnsupportedModel(f"unsupported model: {model!r}")
    if not api_key or not api_key.strip():
        raise ValueError("api_key must not be empty")

    config = await get_ai_config(db, user_id, provider)
    encrypted = encrypt_secret(settings.integration_encryption_key, api_key.strip(), aad=_aad(user_id, provider))
    if config is None:
        config = CandidateAIConfig(user_id=user_id, provider=provider, model=model, encrypted_api_key=encrypted)
        db.add(config)
        await db.flush()
    else:
        config.model = model
        config.encrypted_api_key = encrypted
        await db.flush()
        # `updated_at` has a server-side onupdate — SQLAlchemy expires just
        # that column after an UPDATE (independent of expire_on_commit), and
        # a later plain attribute access can't lazily refresh it inside
        # async SQLAlchemy (MissingGreenlet). Refresh it explicitly here,
        # inside the awaited context, instead of leaving that landmine for
        # whatever reads `config.updated_at` next (e.g. the route response).
        await db.refresh(config)
    return config


async def remove_ai_config(db: AsyncSession, user_id: uuid.UUID, provider: str = PROVIDER_ANTHROPIC) -> bool:
    config = await get_ai_config(db, user_id, provider)
    if config is None:
        return False
    await db.delete(config)
    await db.flush()
    return True


def decrypt_api_key(settings: Settings, config: CandidateAIConfig) -> str:
    """Server-side only — the one place a candidate's key is ever
    decrypted, immediately before an outbound Anthropic API call. Never
    return this value from a route."""
    return decrypt_secret(settings.integration_encryption_key, config.encrypted_api_key, aad=_aad(config.user_id, config.provider))


def manual_search_cooldown_remaining(config: CandidateAIConfig, *, now: datetime | None = None) -> float:
    """Seconds remaining before another manual AI Search is allowed; 0 (or
    negative) means the candidate may search now."""
    if config.last_manual_search_at is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    last = config.last_manual_search_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (now - last).total_seconds()
    return max(0.0, MANUAL_SEARCH_COOLDOWN_SECONDS - elapsed)


async def mark_manual_search(db: AsyncSession, config: CandidateAIConfig) -> None:
    config.last_manual_search_at = datetime.now(timezone.utc)
    await db.flush()
