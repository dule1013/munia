"""Regression coverage for the corrected morning funnel:
discovery -> location eligibility -> cheap triage -> lightweight fit
assessment of surviving promising jobs -> Inbox/Today.

The key fix under test: CandidateJob.triaged_at distinguishes the initial
"uncertain" PLACEHOLDER (set by add_candidate_job on first discovery) from
a REAL triage decision (set by persist_triage_results) — triage_result
alone can't tell them apart, since "uncertain" is also a legitimate real
triage outcome.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.crypto import generate_key
from app.modules.automation.batch import persist_triage_results
from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob


async def make_job(db, *, title: str = "Director of Engineering", company: str = "Acme") -> Job:
    job = Job(id=uuid.uuid4(), canonical_key=f"key-{uuid.uuid4()}", canonical_url=f"https://jobs.example.com/{uuid.uuid4()}", company=company, title=title, location="Remote", source="greenhouse", posting_url=f"https://jobs.example.com/{uuid.uuid4()}", source_metadata={})
    db.add(job)
    await db.flush()
    return job


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, profile={}, master_cv="# CV", profile_yaml="", profile_markdown="", cv_facts={}))
        await db.commit()
        return user


def actionable_for_assessment_query(user_id):
    """Mirrors _candidate_morning_cycle's fit-assessment WHERE clause
    exactly, so these tests exercise the real gate without needing the
    whole morning_run/AI machinery."""
    from sqlalchemy import or_

    from app.modules.pipeline.service import INBOX_TRIAGE_RESULTS

    return select(CandidateJob, Job).join(Job, Job.id == CandidateJob.job_id).where(
        CandidateJob.user_id == user_id,
        CandidateJob.pipeline_status == "Inbox",
        CandidateJob.skipped.is_(False),
        CandidateJob.triaged_at.is_not(None),
        CandidateJob.triage_result.in_(INBOX_TRIAGE_RESULTS),
        or_(CandidateJob.eligibility.is_(None), CandidateJob.eligibility != "ineligible"),
        CandidateJob.ai_fit.is_(None),
    )


async def test_fresh_placeholder_job_is_picked_up_by_triage(api):
    """A freshly discovered CandidateJob (triage_result="uncertain"
    PLACEHOLDER, triaged_at=None) must be processed by real triage, not
    skipped as if already triaged."""
    _, sessions, settings = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job = await make_job(db)
        item = CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Inbox", triage_result="uncertain", triage_reason="Added from discovery; awaiting cheap triage")
        db.add(item)
        await db.commit()
        assert item.triaged_at is None

    data = settings.career_ops_workspace_root / str(user.id) / "data"
    data.mkdir(parents=True)
    data.joinpath("pipeline.md").write_text(f"- [ ] {job.posting_url} | Acme | Director of Engineering | Remote\n")
    data.joinpath("shortlist.md").write_text(f"## Worth evaluating\n### Acme — Director of Engineering\n- Location: Remote\n- Posted: 2026-09-15\n- Source: greenhouse\n- Eligibility: eligible\n- Why it may fit: strong scope match\n- Direct application URL: {job.posting_url}\n## Uncertain\n")

    async with sessions() as db:
        changed = await persist_triage_results(db, user.id, data.parent)
    assert changed == 1

    async with sessions() as db:
        item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == job.id))
        assert item.triage_result == "worth"
        assert item.triaged_at is not None  # now a REAL decision, not the placeholder


async def test_real_triage_worth_makes_the_job_eligible_for_fit_assessment(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job = await make_job(db)
        db.add(CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Inbox", triage_result="worth", triaged_at=datetime.now(timezone.utc)))
        await db.commit()
        rows = (await db.execute(actionable_for_assessment_query(user.id))).all()
    assert len(rows) == 1


async def test_real_triage_uncertain_may_also_proceed_to_fit_assessment(api):
    """Cheap triage's own ambiguity is exactly what the deeper assessment
    exists to resolve — a REAL "uncertain" (triaged_at set) still queues."""
    _, sessions, _ = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job = await make_job(db)
        db.add(CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Inbox", triage_result="uncertain", triaged_at=datetime.now(timezone.utc)))
        await db.commit()
        rows = (await db.execute(actionable_for_assessment_query(user.id))).all()
    assert len(rows) == 1


async def test_placeholder_uncertain_without_real_triage_does_not_proceed(api):
    """The exact bug this fix addresses: a job that has NEVER actually been
    triaged (triaged_at is None) must NOT be treated as if a real "uncertain"
    triage decision qualified it for fit assessment."""
    _, sessions, _ = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job = await make_job(db)
        db.add(CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Inbox", triage_result="uncertain", triaged_at=None))
        await db.commit()
        rows = (await db.execute(actionable_for_assessment_query(user.id))).all()
    assert rows == []


async def test_triage_discard_never_proceeds_to_fit_assessment(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job = await make_job(db)
        db.add(CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Discarded", skipped=True, triage_result="discard", triaged_at=datetime.now(timezone.utc)))
        await db.commit()
        rows = (await db.execute(actionable_for_assessment_query(user.id))).all()
    assert rows == []


async def test_already_triaged_rediscovered_job_is_not_retriaged(api):
    """persist_triage_results must skip a job that was ALREADY really
    triaged (triaged_at set) even if a fresh agent run's shortlist happens
    to mention it again — a second discovery channel rediscovering the same
    job must not reset an already-settled triage decision."""
    _, sessions, settings = api
    user = await seed_user(sessions)
    original_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with sessions() as db:
        job = await make_job(db)
        db.add(CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Inbox", triage_result="worth", triage_reason="original decision", triaged_at=original_time))
        await db.commit()

    data = settings.career_ops_workspace_root / str(user.id) / "data"
    data.mkdir(parents=True)
    data.joinpath("pipeline.md").write_text(f"- [ ] {job.posting_url} | Acme | Director of Engineering | Remote\n")
    # A fresh agent run's shortlist mentions the SAME job again with a
    # DIFFERENT reason — this must be ignored, not overwrite the original.
    data.joinpath("shortlist.md").write_text(f"## Worth evaluating\n### Acme — Director of Engineering\n- Location: Remote\n- Posted: 2026-09-20\n- Source: greenhouse\n- Eligibility: eligible\n- Why it may fit: a DIFFERENT reason from a rerun\n- Direct application URL: {job.posting_url}\n## Uncertain\n")

    async with sessions() as db:
        changed = await persist_triage_results(db, user.id, data.parent)
    assert changed == 0

    async with sessions() as db:
        item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == job.id))
        assert item.triage_reason == "original decision"
        # SQLite doesn't round-trip tzinfo, so compare naive — the important
        # assertion is `changed == 0` above (it was never touched at all).
        assert item.triaged_at.replace(tzinfo=timezone.utc) == original_time


async def test_human_decided_job_is_never_touched_by_triage(api):
    _, sessions, settings = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job = await make_job(db)
        db.add(CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Applied", triage_result="uncertain", triaged_at=None))
        await db.commit()

    data = settings.career_ops_workspace_root / str(user.id) / "data"
    data.mkdir(parents=True)
    data.joinpath("pipeline.md").write_text(f"- [ ] {job.posting_url} | Acme | Director of Engineering | Remote\n")
    data.joinpath("shortlist.md").write_text(f"## Worth evaluating\n### Acme — Director of Engineering\n- Location: Remote\n- Posted: 2026-09-20\n- Source: greenhouse\n- Eligibility: eligible\n- Why it may fit: would overwrite if not protected\n- Direct application URL: {job.posting_url}\n## Uncertain\n")

    async with sessions() as db:
        changed = await persist_triage_results(db, user.id, data.parent)
    assert changed == 0

    async with sessions() as db:
        item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == job.id))
        assert item.pipeline_status == "Applied"
        assert item.triage_result == "uncertain"
        assert item.triaged_at is None


async def test_already_assessed_strong_job_is_not_reassessed_on_rediscovery(api):
    """The fit-assessment query's ai_fit.is_(None) filter is what stops a
    rediscovered-from-another-source already-"strong" job from being
    reassessed for no reason."""
    _, sessions, _ = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job = await make_job(db)
        db.add(CandidateJob(user_id=user.id, job_id=job.id, pipeline_status="Inbox", triage_result="worth", triaged_at=datetime.now(timezone.utc), ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc)))
        await db.commit()
        rows = (await db.execute(actionable_for_assessment_query(user.id))).all()
    assert rows == []  # already assessed — not queued again
