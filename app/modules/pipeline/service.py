import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.schemas import CandidateJobCreate, CandidateJobUpdate

# Triage results that keep a CandidateJob "actionable" — a hard "discard"
# from triage is excluded from both Inbox and Today, matching "hard rejects
# excluded" (Phase 5 follow-up, Today/Inbox semantics).
INBOX_TRIAGE_RESULTS = ("worth", "uncertain")

# "uncertain" is the ONLY placeholder value discovery paths ever seed
# (linkedin_ingest/watchlist_scan/discovery.routes all pass exactly this on
# every call, including rediscovery — see their CandidateJobCreate calls).
# A stored triage_result outside this set is a REAL decision automation
# already made (triage_all set "worth"/"discard"), not a placeholder —
# add_candidate_job must not reset it back to "uncertain" just because a
# second discovery channel found the same job before Today/Inbox ever see
# a stable answer for it.
_PLACEHOLDER_TRIAGE_RESULTS = (None, "uncertain")

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
    if not has_candidate_decision(item) and item.triage_result in _PLACEHOLDER_TRIAGE_RESULTS:
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


# ── Today/Inbox query semantics (Phase 5 follow-up) ─────────────────────────
#
# Inbox = "this may be worth your attention": still sitting in the default
# "Inbox" pipeline_status (a human hasn't moved/applied/dismissed it), not
# skipped, and triage didn't hard-discard it. Deliberately broader than
# Today — plausible/uncertain jobs live here too.
#
# Today = only the strongest, still-actionable opportunities: the same
# Inbox criteria, PLUS the lightweight AI fit assessment (see
# app.modules.pipeline.fit_assessment) says "strong". A job with no
# assessment yet (ai_fit is None) never qualifies for Today just because it
# looks plausible — it stays in Inbox until a real assessment says "strong".
#
# Both fall out naturally the moment a human acts: update_candidate_job
# changing pipeline_status away from "Inbox" (Applied, Discarded, ...) or
# setting `skipped` removes the item from both queries immediately, and
# because add_candidate_job/apply_assessment never touch an item once
# has_candidate_decision(item) is true, rediscovery can never resurrect it.
def _actionable_filters(user_id: uuid.UUID):
    return (CandidateJob.user_id == user_id, CandidateJob.pipeline_status == "Inbox", CandidateJob.skipped.is_(False), CandidateJob.triage_result.in_(INBOX_TRIAGE_RESULTS))


async def list_inbox(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[CandidateJob, Job]]:
    rows = await db.execute(select(CandidateJob, Job).join(Job, Job.id == CandidateJob.job_id).where(*_actionable_filters(user_id)).order_by(CandidateJob.created_at.desc()))
    return list(rows.all())


async def list_today(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[CandidateJob, Job]]:
    """Cumulative by construction — no calendar-day filter at all. An item
    stays here across any number of days until a human action (or a later
    re-assessment, which apply_assessment refuses once has_candidate_decision
    is true) removes it. Newest-qualifying-first via ai_fit_assessed_at."""
    rows = await db.execute(select(CandidateJob, Job).join(Job, Job.id == CandidateJob.job_id).where(*_actionable_filters(user_id), CandidateJob.ai_fit == "strong").order_by(CandidateJob.ai_fit_assessed_at.desc()))
    return list(rows.all())


# How wide a window (from the most recent qualifying assessment backward)
# counts as "the latest morning cycle" for the NEW-vs-CURRENT distinction —
# a deliberate, documented heuristic rather than a new run-tracking table
# (Phase 5 follow-up: "do not build a complex analytics/event system"). A
# single morning cycle is expected to finish in well under this window, and
# cycles are expected to run roughly once/day, so this reliably separates
# "qualified in the latest completed run" from "qualified in an earlier one"
# without needing to record which specific run produced which assessment.
NEW_WINDOW_HOURS = 20.0


async def today_summary(db: AsyncSession, user_id: uuid.UUID, *, new_window_hours: float = NEW_WINDOW_HOURS) -> dict:
    today_rows = await list_today(db, user_id)
    current = len(today_rows)
    if not today_rows:
        return {"new": 0, "current": 0}
    latest = max(item.ai_fit_assessed_at for item, _ in today_rows)
    cutoff = latest - timedelta(hours=new_window_hours)
    new = sum(1 for item, _ in today_rows if item.ai_fit_assessed_at >= cutoff)
    return {"new": new, "current": current}
