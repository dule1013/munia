import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.modules.candidates.models import User
from app.modules.discovery.models import MorningRun
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.fit_assessment import apply_assessment
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.schemas import CandidateJobCreate, CandidateJobUpdate
from app.modules.pipeline.service import add_candidate_job, list_inbox, list_today, today_summary, update_candidate_job


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


async def make_job(db, *, title: str, company: str = "Acme"):
    payload = JobIngest(company=company, title=title, source="greenhouse", posting_url=f"https://job-boards.greenhouse.io/{company}/{uuid.uuid4()}", direct_application_url=f"https://job-boards.greenhouse.io/{company}/{uuid.uuid4()}")
    job, _, _ = await ingest_discovery(db, payload, method="reverse_ats")
    return job


async def seed_candidate_job(sessions, user, *, title: str, triage_result: str = "worth", ai_fit: str | None = None, ai_fit_assessed_at: datetime | None = None, ai_fit_run_id=None, pipeline_status: str = "Inbox", skipped: bool = False):
    async with sessions() as db:
        job = await make_job(db, title=title)
        await db.commit()
        item = CandidateJob(user_id=user.id, job_id=job.id, triage_result=triage_result, ai_fit=ai_fit, ai_fit_assessed_at=ai_fit_assessed_at, ai_fit_run_id=ai_fit_run_id, pipeline_status=pipeline_status, skipped=skipped)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item.id


async def test_strong_job_enters_inbox_and_today(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    now = datetime.now(timezone.utc)
    await seed_candidate_job(sessions, user, title="Director of Engineering", triage_result="worth", ai_fit="strong", ai_fit_assessed_at=now)

    async with sessions() as db:
        inbox = await list_inbox(db, user.id)
        today = await list_today(db, user.id)
    assert len(inbox) == 1
    assert len(today) == 1


async def test_plausible_job_enters_inbox_only(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    await seed_candidate_job(sessions, user, title="Head of Engineering", triage_result="worth", ai_fit="plausible", ai_fit_assessed_at=datetime.now(timezone.utc))

    async with sessions() as db:
        inbox = await list_inbox(db, user.id)
        today = await list_today(db, user.id)
    assert len(inbox) == 1
    assert len(today) == 0


async def test_uncertain_triage_job_enters_inbox_only(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    await seed_candidate_job(sessions, user, title="Engineering Manager", triage_result="uncertain", ai_fit=None)

    async with sessions() as db:
        inbox = await list_inbox(db, user.id)
        today = await list_today(db, user.id)
    assert len(inbox) == 1
    assert len(today) == 0


async def test_hard_reject_enters_neither(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    await seed_candidate_job(sessions, user, title="Junior Engineer", triage_result="discard")

    async with sessions() as db:
        inbox = await list_inbox(db, user.id)
        today = await list_today(db, user.id)
    assert inbox == []
    assert today == []


async def test_no_ai_assessment_does_not_qualify_for_today(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    await seed_candidate_job(sessions, user, title="Director of Engineering", triage_result="worth", ai_fit=None)

    async with sessions() as db:
        today = await list_today(db, user.id)
    assert today == []


async def test_today_is_cumulative_across_days_newest_first(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    now = datetime.now(timezone.utc)
    await seed_candidate_job(sessions, user, title="A", ai_fit="strong", ai_fit_assessed_at=now - timedelta(days=2))
    await seed_candidate_job(sessions, user, title="B", ai_fit="strong", ai_fit_assessed_at=now - timedelta(days=2, minutes=1))
    await seed_candidate_job(sessions, user, title="C", ai_fit="strong", ai_fit_assessed_at=now - timedelta(days=1))

    async with sessions() as db:
        today = await list_today(db, user.id)
    titles = [job.title for _, job in today]
    assert titles == ["C", "A", "B"]  # newest qualifying first; C (day-1) before A/B (day-2, A after B)


async def test_applied_leaves_today(api):
    client, sessions, _ = api
    user = await seed_user(sessions)
    cj_id = await seed_candidate_job(sessions, user, title="Director of Engineering", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc))

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        await update_candidate_job(db, item, CandidateJobUpdate(pipeline_status="Applied"))

    async with sessions() as db:
        today = await list_today(db, user.id)
        inbox = await list_inbox(db, user.id)
    assert today == []
    assert inbox == []


async def test_dismissed_leaves_today(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    cj_id = await seed_candidate_job(sessions, user, title="Director of Engineering", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc))

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        await update_candidate_job(db, item, CandidateJobUpdate(skipped=True))

    async with sessions() as db:
        today = await list_today(db, user.id)
    assert today == []


async def test_rediscovery_does_not_duplicate_today_item(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    now = datetime.now(timezone.utc)

    async with sessions() as db:
        job = await make_job(db, title="Director of Engineering")
        await db.commit()
        item = CandidateJob(user_id=user.id, job_id=job.id, triage_result="worth", ai_fit="strong", ai_fit_assessed_at=now)
        db.add(item)
        await db.commit()

    # Rediscovering the SAME job (e.g. a second reverse-ATS pass) should not
    # create a second CandidateJob nor duplicate the Today entry.
    async with sessions() as db:
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id))

    async with sessions() as db:
        today = await list_today(db, user.id)
    assert len(today) == 1


async def test_human_decision_survives_rediscovery_and_stays_out_of_today(api):
    _, sessions, _ = api
    user = await seed_user(sessions)

    async with sessions() as db:
        job = await make_job(db, title="Director of Engineering")
        await db.commit()
        item = CandidateJob(user_id=user.id, job_id=job.id, triage_result="worth", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc), pipeline_status="Applied")
        db.add(item)
        await db.commit()

    async with sessions() as db:
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain"))

    async with sessions() as db:
        item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == job.id))
        assert item.pipeline_status == "Applied"
        today = await list_today(db, user.id)
    assert today == []


async def test_candidate_isolation_for_today_and_inbox(api):
    _, sessions, _ = api
    user_a = await seed_user(sessions, "clerk-a")
    user_b = await seed_user(sessions, "clerk-b")
    await seed_candidate_job(sessions, user_a, title="A's job", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc))

    async with sessions() as db:
        today_a = await list_today(db, user_a.id)
        today_b = await list_today(db, user_b.id)
    assert len(today_a) == 1
    assert len(today_b) == 0


async def make_morning_run(sessions, *, status: str = "completed") -> uuid.UUID:
    async with sessions() as db:
        run = MorningRun(id=uuid.uuid4(), status=status, finished_at=datetime.now(timezone.utc))
        db.add(run)
        await db.commit()
        return run.id


async def test_today_summary_new_is_tied_to_the_latest_completed_run_not_a_time_window(api):
    """Regression: a rolling time-window heuristic would miscount under
    delayed/manual/retried runs. "new" must mean "ai_fit_run_id == the
    latest completed run's id", nothing else."""
    _, sessions, _ = api
    user = await seed_user(sessions)
    old_run = await make_morning_run(sessions)
    latest_run = await make_morning_run(sessions)

    await seed_candidate_job(sessions, user, title="Old", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc), ai_fit_run_id=old_run)
    await seed_candidate_job(sessions, user, title="New1", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc), ai_fit_run_id=latest_run)
    await seed_candidate_job(sessions, user, title="New2", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc), ai_fit_run_id=latest_run)

    async with sessions() as db:
        summary = await today_summary(db, user.id)
    assert summary["current"] == 3
    assert summary["new"] == 2


async def test_no_completed_run_yet_means_zero_new(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    await seed_candidate_job(sessions, user, title="A", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc))
    async with sessions() as db:
        summary = await today_summary(db, user.id)
    assert summary == {"new": 0, "current": 1}


async def test_a_run_still_in_progress_is_not_used_as_the_reference_run(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    running_run = await make_morning_run(sessions, status="running")
    await seed_candidate_job(sessions, user, title="A", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc), ai_fit_run_id=running_run)
    async with sessions() as db:
        summary = await today_summary(db, user.id)
    assert summary["new"] == 0  # the run isn't "completed" yet, so it's never the reference run


async def test_rediscovery_reassessment_does_not_make_an_old_strong_job_new_again(api):
    """A job already strong from run 1; run 2 reassesses it and confirms
    "strong" again — apply_assessment must NOT move its ai_fit_run_id to
    run 2, or it would incorrectly count as "new" in run 2's summary."""
    _, sessions, _ = api
    user = await seed_user(sessions)
    run1 = await make_morning_run(sessions)
    cj_id = await seed_candidate_job(sessions, user, title="A", ai_fit="strong", ai_fit_assessed_at=datetime.now(timezone.utc) - timedelta(days=1), ai_fit_run_id=run1)
    run2 = await make_morning_run(sessions)

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        await apply_assessment(db, item, {"fit": "strong", "reason": "still a great match", "confidence": "high"}, run_id=run2)
        await db.commit()
        await db.refresh(item)
    assert item.ai_fit_run_id == run1  # unchanged — still attributed to when it FIRST became strong

    async with sessions() as db:
        summary = await today_summary(db, user.id)
    assert summary["new"] == 0  # run2 is latest, but this job isn't newly strong under it


async def test_plausible_becoming_strong_during_the_current_run_counts_as_new(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    cj_id = await seed_candidate_job(sessions, user, title="A", triage_result="worth", ai_fit="plausible", ai_fit_assessed_at=datetime.now(timezone.utc) - timedelta(days=1))
    run = await make_morning_run(sessions)

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        await apply_assessment(db, item, {"fit": "strong", "reason": "now a clear match", "confidence": "high"}, run_id=run)
        await db.commit()

    async with sessions() as db:
        summary = await today_summary(db, user.id)
    assert summary["new"] == 1
    assert summary["current"] == 1
