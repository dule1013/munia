import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.time import utcnow
from app.modules.integrations.models import CandidateIntegration, OAuthState


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)

OAUTH_STATE_TTL_MINUTES = 10
# Bounded so the row can't grow forever; only used to skip re-fetching a
# message we already parsed on the very next sync, never for correctness
# (see CandidateIntegration's docstring).
MAX_TRACKED_MESSAGE_IDS = 500


def _aad(user_id: uuid.UUID, provider: str) -> str:
    return f"{user_id}:{provider}"


async def get_integration(db: AsyncSession, user_id: uuid.UUID, provider: str) -> CandidateIntegration | None:
    return await db.scalar(select(CandidateIntegration).where(CandidateIntegration.user_id == user_id, CandidateIntegration.provider == provider))


async def create_oauth_state(db: AsyncSession, user_id: uuid.UUID, provider: str) -> OAuthState:
    state = OAuthState(state=secrets.token_urlsafe(32), user_id=user_id, provider=provider, expires_at=utcnow() + timedelta(minutes=OAUTH_STATE_TTL_MINUTES))
    db.add(state)
    await db.commit()
    return state


async def consume_oauth_state(db: AsyncSession, state_value: str, provider: str) -> OAuthState | None:
    """One-time use: a state is only ever valid for a single callback. Returns
    None on any mismatch (unknown, wrong provider, expired, already used) —
    the caller treats all of those identically (reject the callback)."""
    row = await db.scalar(select(OAuthState).where(OAuthState.state == state_value, OAuthState.provider == provider))
    if row is None or row.consumed_at is not None or _as_aware(row.expires_at) < utcnow():
        return None
    row.consumed_at = utcnow()
    await db.commit()
    return row


async def store_tokens(db: AsyncSession, settings: Settings, *, user_id: uuid.UUID, provider: str, refresh_token: str, account_email: str | None, scopes: str) -> CandidateIntegration:
    encrypted = encrypt_secret(settings.integration_encryption_key, json.dumps({"refresh_token": refresh_token}), aad=_aad(user_id, provider))
    integration = await get_integration(db, user_id, provider)
    if integration is None:
        integration = CandidateIntegration(user_id=user_id, provider=provider)
        db.add(integration)
    integration.status = "connected"
    integration.account_email = account_email
    integration.scopes = scopes
    integration.encrypted_credentials = encrypted
    integration.last_error = None
    integration.last_sync_status = None
    integration.sync_cursor = {}
    await db.commit()
    await db.refresh(integration)
    return integration


def decrypt_refresh_token(settings: Settings, integration: CandidateIntegration) -> str:
    if not integration.encrypted_credentials:
        raise ValueError("integration has no stored credentials")
    payload = json.loads(decrypt_secret(settings.integration_encryption_key, integration.encrypted_credentials, aad=_aad(integration.user_id, integration.provider)))
    return payload["refresh_token"]


async def disconnect_integration(db: AsyncSession, integration: CandidateIntegration) -> None:
    integration.status = "disconnected"
    integration.encrypted_credentials = None
    integration.sync_cursor = {}
    integration.last_error = None
    integration.last_sync_status = None
    await db.commit()


async def mark_sync_result(db: AsyncSession, integration: CandidateIntegration, *, ok: bool, error: str | None, processed_message_ids: list[str] | None = None) -> None:
    integration.last_sync_at = utcnow()
    integration.last_sync_status = "ok" if ok else "error"
    integration.last_error = error
    if ok:
        integration.status = "connected"
    elif error and "invalid_grant" in error:
        # The provider explicitly told us the refresh token no longer works —
        # surface this as a distinct, actionable state rather than a generic error.
        integration.status = "revoked"
    else:
        integration.status = "error"
    if processed_message_ids is not None:
        existing = list((integration.sync_cursor or {}).get("processed_message_ids") or [])
        merged = list(dict.fromkeys(existing + processed_message_ids))[-MAX_TRACKED_MESSAGE_IDS:]
        integration.sync_cursor = {**(integration.sync_cursor or {}), "processed_message_ids": merged}
    await db.commit()
