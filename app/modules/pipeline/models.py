import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class CandidateJob(Base):
    __tablename__ = "candidate_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_candidate_jobs_user_job"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    eligibility: Mapped[str | None] = mapped_column(String(100))
    triage_result: Mapped[str | None] = mapped_column(String(30), index=True)
    triage_reason: Mapped[str | None] = mapped_column(Text)
    # Distinguishes the initial "uncertain" PLACEHOLDER (set by
    # add_candidate_job on first discovery, before any real triage has run)
    # from a REAL triage decision — triage_result alone can't tell them
    # apart, since "uncertain" is also a legitimate real outcome
    # (persist_triage_results writes it from the shortlist's "Uncertain"
    # section). NULL = never really triaged yet; set = triage actually ran.
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    triage_metadata: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    fit_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    recommendation: Mapped[str | None] = mapped_column(String(100))
    pipeline_status: Mapped[str] = mapped_column(String(50), default="Inbox", index=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lightweight morning "is this worth Today?" assessment (Phase 5 follow-up
    # §F) — deliberately separate from fit_score/recommendation/evaluated_at
    # above, which belong to the full, human-triggered Evaluate action. Never
    # confuse the two: ai_fit is cheap/automated, fit_score is the real thing.
    ai_fit: Mapped[str | None] = mapped_column(String(20), index=True)  # "strong" | "plausible" | "reject"
    ai_fit_reason: Mapped[str | None] = mapped_column(Text)
    ai_fit_confidence: Mapped[str | None] = mapped_column(String(10))  # "high" | "low"
    ai_fit_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Which MorningRun most recently made this job NEWLY "strong" — set only
    # on a transition INTO "strong" (see fit_assessment.apply_assessment),
    # never touched by a reassessment that merely confirms it's still
    # "strong". This is what lets Today's "N new" count answer "newly
    # qualified during the latest completed run", not "assessed recently".
    ai_fit_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("morning_runs.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidate_jobs.id", ondelete="CASCADE"), index=True)
    report_number: Mapped[int | None] = mapped_column(index=True)
    score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    recommendation: Mapped[str | None] = mapped_column(String(100))
    report_markdown: Mapped[str] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
