import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_jobs_canonical_url"),
        UniqueConstraint("canonical_key", name="uq_jobs_canonical_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_key: Mapped[str] = mapped_column(String(512))
    canonical_url: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    location: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), default="unknown")
    external_source_id: Mapped[str | None] = mapped_column(String(255), index=True)
    posting_url: Mapped[str] = mapped_column(Text)
    direct_application_url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobDiscovery(Base):
    """One observation of a canonical Job through a specific source/method.

    A Job may be discovered multiple times, through multiple channels (LinkedIn
    alert email, a Greenhouse reverse-network scan, a watched company's careers
    page, an AI web search, ...). Each distinct (source, method, source_url)
    combination gets its own row; re-observing the same combination just bumps
    `last_seen_at` instead of duplicating. `source` is WHERE the job lives
    (linkedin, greenhouse, lever, ...); `method` is HOW Munia found it
    (email_alert, reverse_ats, company_watchlist, web_search, manual,
    legacy_import). See app.modules.discovery.sources for the catalog of
    valid values.
    """

    __tablename__ = "job_discoveries"
    __table_args__ = (
        UniqueConstraint("job_id", "source", "method", "source_url", name="uq_job_discoveries_job_source_method_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    # Nullable: some discovery methods aren't candidate-scoped (e.g. a shared
    # reverse-ATS network scan run on behalf of a representative candidate).
    # Set to SET NULL rather than CASCADE so deleting a user never deletes the
    # shared Job's discovery history.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    method: Mapped[str] = mapped_column(String(50), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(255))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
