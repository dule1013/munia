import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.candidates.location_eligibility import build_location_config_from_profile, classify_location_eligibility
from app.modules.candidates.service import get_profile
from app.modules.discovery.models import MorningRun
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
# skipped, not location-ineligible, and triage didn't hard-discard it.
# Deliberately broader than Today — plausible/uncertain jobs live here too.
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
    return (
        CandidateJob.user_id == user_id,
        CandidateJob.pipeline_status == "Inbox",
        CandidateJob.skipped.is_(False),
        CandidateJob.triage_result.in_(INBOX_TRIAGE_RESULTS),
        # NULL-safe: plain `!= "ineligible"` would silently exclude every
        # row where eligibility is still unset (NULL != x is NULL, not
        # true, in SQL) — most CandidateJobs before the location gate runs.
        or_(CandidateJob.eligibility.is_(None), CandidateJob.eligibility != "ineligible"),
    )


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


async def today_summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """"current" = every strong actionable opportunity right now (list_today
    length). "new" = of those, how many carry ai_fit_run_id pointing at the
    LATEST *completed* (or completed_with_warnings) MorningRun — i.e. newly
    qualified during that specific run, not merely "recently assessed"
    (fixes the earlier rolling-time-window heuristic, which broke under
    delayed/manual/retried runs). A job already strong from an older run
    that this run's reassessment simply reconfirmed does NOT count as new
    (apply_assessment only sets ai_fit_run_id on an actual plausible/reject
    -> strong transition). No morning run has completed yet -> new is 0."""
    today_rows = await list_today(db, user_id)
    current = len(today_rows)
    latest_run = await db.scalar(select(MorningRun).where(MorningRun.status.in_(("completed", "completed_with_warnings"))).order_by(MorningRun.finished_at.desc()).limit(1))
    if not latest_run:
        return {"new": 0, "current": current}
    new = sum(1 for item, _ in today_rows if item.ai_fit_run_id == latest_run.id)
    return {"new": new, "current": current}


async def apply_location_eligibility(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Phase 5 follow-up §3 — wires the deterministic location classifier
    into the real per-candidate pipeline, not just a tested-in-isolation
    helper. Runs on every still-undecided CandidateJob missing an
    eligibility verdict; an "ineligible" result ALSO hard-discards the item
    (triage_result="discard") so it's excluded from Inbox/Today and never
    reaches the (expensive) lightweight AI fit assessment — matching "should
    not proceed into expensive AI assessment... should not appear in Today...
    should not be promoted as an actionable Inbox match". "eligible"/
    "plausible" jobs are left exactly as found for triage/assessment to
    continue processing. Never touches a CandidateJob a human (or an
    existing real decision) already owns."""
    profile = await get_profile(db, user_id)
    config = build_location_config_from_profile(profile.profile if profile else {})
    rows = await db.execute(select(CandidateJob, Job).join(Job, Job.id == CandidateJob.job_id).where(CandidateJob.user_id == user_id, CandidateJob.eligibility.is_(None)))
    classified = 0
    for item, job in rows.all():
        if has_candidate_decision(item):
            continue
        tier, reason = classify_location_eligibility(job.location, job.description or "", config)
        item.eligibility = tier
        if tier == "ineligible":
            item.triage_result = "discard"
            item.triage_reason = reason
            # Effectively already "triaged" by location alone — never needs
            # AI triage/fit-assessment, and must not sit in a queryable
            # "still needs triage" (triaged_at IS NULL) state forever.
            item.triaged_at = datetime.now(timezone.utc)
        classified += 1
    await db.commit()
    return classified
