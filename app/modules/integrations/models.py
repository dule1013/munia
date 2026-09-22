import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class CandidateIntegration(Base):
    """A candidate's own connection to a third-party account (Gmail today).

    One row per (user, provider). `encrypted_credentials` NEVER holds a
    plaintext token — see app/core/crypto.py — and nothing here (or anywhere
    upstream: CandidateProfile, profile.yml, portals.yml, workspace files)
    stores Gmail credentials any other way. `sync_cursor` is a small,
    bounded efficiency hint (which messages were already fetched), NOT a
    correctness requirement: re-processing a message is idempotent by
    construction through JobDiscovery's unique constraint, so losing this
    cursor just costs some wasted Gmail API calls on the next sync, never a
    duplicate Job.
    """

    __tablename__ = "candidate_integrations"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_candidate_integrations_user_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="disconnected", index=True)
    account_email: Mapped[str | None] = mapped_column(String(320))
    scopes: Mapped[str | None] = mapped_column(String(500))
    # base64(nonce || AES-256-GCM ciphertext || tag) of a small JSON blob
    # ({"refresh_token": "..."}). See app/core/crypto.py.
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    sync_cursor: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OAuthState(Base):
    """Short-lived, one-time CSRF binding between an OAuth `state` value and
    the Munia user who initiated the connection. Necessary because the
    provider's redirect back to our /callback carries no Clerk session —
    this row is how we know which candidate a given `code` belongs to, and
    that the callback wasn't forged/replayed."""

    __tablename__ = "oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
