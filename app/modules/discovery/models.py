import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    request: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON_TYPE)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WatchedCompany(Base):
    """A candidate's Company Watchlist entry (Phase 5 §4).

    Private, per-candidate configuration: the canonical Job records that
    scanning a watched company eventually produces are shared globally like
    any other Job, but the watchlist entry itself (which companies a candidate
    cares about, priority, scan status) is not. `company_key` is a normalized
    (casefold/collapsed-whitespace) form of `company_name` used both for
    dedup within one candidate's list and for grouping identical watch
    targets across candidates so a shared company is only scanned once
    (see discovery.watchlist_service.distinct_scan_targets).
    """

    __tablename__ = "watched_companies"
    __table_args__ = (UniqueConstraint("user_id", "company_key", name="uq_watched_companies_user_company"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    company_key: Mapped[str] = mapped_column(String(255), index=True)
    careers_url: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(100))
    provider_tenant_id: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_status: Mapped[str | None] = mapped_column(String(30))
    last_scan_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MorningRun(Base):
    """One global morning automation cycle (Phase 5 follow-up §E) — NOT
    per-candidate (DiscoveryRun is, and doesn't fit a shared cycle that does
    per-candidate work internally). Deliberately minimal: this exists to
    answer exactly two questions precisely — "how many strong opportunities
    are currently actionable" (CandidateJob.ai_fit == "strong", no run
    needed) and "how many of those newly became strong during the latest
    completed run" (CandidateJob.ai_fit_run_id == this run's id) — not to be
    a general automation event/analytics system."""

    __tablename__ = "morning_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)  # running | completed | completed_with_warnings | failed
    summary: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AtsScanCursor(Base):
    """One row per reverse-ATS source (Phase 5 follow-up §C) — the
    persistent position deterministic morning rotation resumes from. Global,
    not per-candidate: the reverse-network scan itself is shared discovery
    work, same as the canonical Job it produces. See
    app.modules.discovery.ats_rotation for the offset/wraparound math."""

    __tablename__ = "ats_scan_cursors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    next_offset: Mapped[int] = mapped_column(Integer, default=0)
    dataset_size: Mapped[int | None] = mapped_column(Integer)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
