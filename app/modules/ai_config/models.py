import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CandidateAIConfig(Base):
    """A candidate's OWN AI provider credential (Phase 5 follow-up).

    Munia is a private ~4-5 person tool — there is deliberately no shared/
    global API key. Each candidate brings their own, exactly like Gmail
    OAuth: encrypted at rest (app/core/crypto.py, same
    INTEGRATION_ENCRYPTION_KEY), bound to (user_id, provider) via AAD so a
    ciphertext can't be replayed onto another candidate's row, and NEVER
    stored in CandidateProfile/profile.yml/portals.yml/workspace files or
    returned by any API response after saving.

    One row per (user, provider) — `provider` exists so another provider
    (OpenAI, Gemini, ...) can be added later without a schema change, even
    though only "anthropic" is accepted today (see ai_config.service).
    """

    __tablename__ = "candidate_ai_configs"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_candidate_ai_configs_user_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    model: Mapped[str] = mapped_column(String(100))
    # base64(nonce || AES-256-GCM ciphertext || tag) of the raw API key string.
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    # Cheap, in-DB cooldown for manual "AI Search" clicks (Phase 5 §2) — not
    # a precise quota system, just enough to stop a candidate from
    # accidentally hammering their own (or, worse, a shared) key.
    last_manual_search_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
