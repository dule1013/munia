import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.schemas import CandidateJobCreate, CandidateJobUpdate

# Field ownership on CandidateJob (Phase 5 Checkpoint E §1). Repeated
# discovery of the same Job (LinkedIn, watchlist, reverse-ATS, level3, ...)
# must be idempotent with respect to anything below "already decided":
#
#   A. Discovery/machine-owned — safe to refresh on every rediscovery, no
#      guard needed: Job.* (governed by ingest_discovery's own strong/weak
#      rules), CandidateJob.triage_metadata (bookkeeping only).
#   B. Triage/automation-owned — the FIRST discovery may set a placeholder
#      (eligibility/triage_result="uncertain"/triage_reason); once a real
#      decision has been recorded (by triage, evaluation, or the candidate),
#      later rediscovery must not reset it back to that placeholder.
#   C. Human-owned (and automation outcomes a human already saw/acted on) —
#      pipeline_status once it has left "Inbox", saved, skipped, notes,
#      fit_score, recommendation, evaluated_at, applied_at. Never touched by
#      add_candidate_job; only by update_candidate_job (an explicit human/UI
#      write) or the evaluate/triage flows that own them.
def has_candidate_decision(item: CandidateJob) -> bool:
    """True once this CandidateJob reflects ANY outcome beyond the fresh
    "just discovered, awaiting triage" default — a human pipeline move, a
    save, a dismissal, notes, or a completed evaluation/triage. Rediscovery
    must leave a job in this state alone.

    `pipeline_status` is checked against `(None, "Inbox")` rather than just
    `"Inbox"`: a brand-new, not-yet-flushed CandidateJob has `None` for every
    column with a Python-side `default=` (SQLAlchemy only applies those
    during flush), so comparing with a bare `!=` would treat every freshly
    constructed item as if it already had a decision.
    """
    return bool(
        item.pipeline_status not in (None, "Inbox")
        or item.saved
        or item.skipped
        or item.notes
        or item.applied_at is not None
        or item.evaluated_at is not None
        or item.fit_score is not None
        or item.recommendation is not None
    )


async def candidate_job_for_user(db: AsyncSession, user_id: uuid.UUID, candidate_job_id: uuid.UUID) -> CandidateJob | None:
    return await db.scalar(select(CandidateJob).where(CandidateJob.id == candidate_job_id, CandidateJob.user_id == user_id))


async def add_candidate_job(db: AsyncSession, user_id: uuid.UUID, payload: CandidateJobCreate) -> CandidateJob:
    """The discovery-facing entry point: attach `payload.job_id` to this
    candidate's pipeline. Creates a fresh CandidateJob (or refreshes a
    still-undecided one's machine-owned triage fields) on first sight of a
    job; once the candidate/automation has actually decided something about
    it, rediscovering it through a different channel is a no-op on those
    fields — see has_candidate_decision."""
    job = await db.get(Job, payload.job_id)
    if not job:
        raise ValueError("job not found")
    item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user_id, CandidateJob.job_id == payload.job_id))
    if item is None:
        item = CandidateJob(user_id=user_id, job_id=payload.job_id)
        db.add(item)
    if not has_candidate_decision(item):
        item.eligibility = payload.eligibility
        item.triage_result = payload.triage_result
        item.triage_reason = payload.triage_reason
    await db.commit()
    await db.refresh(item)
    return item


async def update_candidate_job(db: AsyncSession, item: CandidateJob, payload: CandidateJobUpdate) -> CandidateJob:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item
