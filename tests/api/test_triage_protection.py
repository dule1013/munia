"""Rediscovery of an already-decided Job must be idempotent w.r.t. that
decision (Phase 5 Checkpoint E §1). Covers both discovery-facing write
paths: pipeline.service.add_candidate_job (LinkedIn/watchlist/manual-add)
and migration.service.import_pipeline (direct_discovery/reverse_discovery/
level3_all's recurring re-import of pipeline.md).
"""

import uuid
from datetime import datetime
from pathlib import Path

from app.core.time import utcnow
from app.modules.candidates.models import User
from app.modules.jobs.models import Job
from app.modules.jobs.service import ingest_discovery
from app.modules.jobs.schemas import JobIngest
from app.modules.migration.service import import_pipeline
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job, has_candidate_decision


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


async def make_job(sessions) -> Job:
    async with sessions() as db:
        job, _, _ = await ingest_discovery(db, JobIngest(company="Acme", title="Director of Engineering", location="Remote", source="greenhouse", posting_url="https://job-boards.greenhouse.io/acme/1", direct_application_url="https://job-boards.greenhouse.io/acme/1"), method="reverse_ats")
        await db.commit()
        return job


def test_has_candidate_decision_defaults_false():
    item = CandidateJob(pipeline_status="Inbox", saved=False, skipped=False, notes="", applied_at=None, evaluated_at=None, fit_score=None, recommendation=None)
    assert has_candidate_decision(item) is False


def test_has_candidate_decision_true_for_each_protected_field():
    base = dict(pipeline_status="Inbox", saved=False, skipped=False, notes="", applied_at=None, evaluated_at=None, fit_score=None, recommendation=None)
    assert has_candidate_decision(CandidateJob(**{**base, "pipeline_status": "Worth Evaluating"})) is True
    assert has_candidate_decision(CandidateJob(**{**base, "saved": True})) is True
    assert has_candidate_decision(CandidateJob(**{**base, "skipped": True})) is True
    assert has_candidate_decision(CandidateJob(**{**base, "notes": "looks interesting"})) is True
    assert has_candidate_decision(CandidateJob(**{**base, "applied_at": utcnow()})) is True
    assert has_candidate_decision(CandidateJob(**{**base, "evaluated_at": utcnow()})) is True
    assert has_candidate_decision(CandidateJob(**{**base, "fit_score": 4.2})) is True
    assert has_candidate_decision(CandidateJob(**{**base, "recommendation": "Apply"})) is True


async def test_add_candidate_job_sets_placeholder_on_first_sight(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    job = await make_job(sessions)
    async with sessions() as db:
        item = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added from candidate discovery; awaiting cheap triage"))
        assert item.triage_result == "uncertain"
        assert item.pipeline_status == "Inbox"


async def test_add_candidate_job_does_not_reset_a_human_saved_job(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    job = await make_job(sessions)
    async with sessions() as db:
        item = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added; awaiting triage"))
        item.saved = True
        item.triage_result = "worth"
        item.triage_reason = "Strong fit — candidate saved it"
        await db.commit()

    # Rediscovered through a second channel (e.g. LinkedIn after Greenhouse).
    async with sessions() as db:
        item2 = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added; awaiting triage"))
        assert item2.saved is True
        assert item2.triage_result == "worth"
        assert item2.triage_reason == "Strong fit — candidate saved it"


async def test_add_candidate_job_does_not_reset_applied_job(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    job = await make_job(sessions)
    async with sessions() as db:
        item = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added; awaiting triage"))
        item.pipeline_status = "Applied"
        item.applied_at = utcnow()
        item.triage_result = "worth"
        await db.commit()

    async with sessions() as db:
        item2 = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added; awaiting triage"))
        assert item2.pipeline_status == "Applied"
        assert item2.applied_at is not None
        assert item2.triage_result == "worth"


async def test_add_candidate_job_does_not_reset_manually_edited_notes(api):
    _, sessions, _ = api
    user = await seed_user(sessions)
    job = await make_job(sessions)
    async with sessions() as db:
        item = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added; awaiting triage"))
        item.notes = "Recruiter reached out directly, escalate."
        item.triage_reason = "Escalated manually"
        await db.commit()

    async with sessions() as db:
        item2 = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added; awaiting triage"))
        assert item2.notes == "Recruiter reached out directly, escalate."
        assert item2.triage_reason == "Escalated manually"


async def test_add_candidate_job_still_refreshes_undecided_placeholder(api):
    """An Inbox item with no decision yet SHOULD still pick up a fresher
    triage_result/reason from a later discovery pass — the guard protects
    decisions, not the very first machine-owned placeholder."""
    _, sessions, _ = api
    user = await seed_user(sessions)
    job = await make_job(sessions)
    async with sessions() as db:
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added; awaiting triage"))

    async with sessions() as db:
        item2 = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, eligibility="eligible", triage_result="uncertain", triage_reason="Rediscovered with fresher metadata"))
        assert item2.triage_reason == "Rediscovered with fresher metadata"
        assert item2.eligibility == "eligible"


async def test_import_pipeline_does_not_reset_evaluated_job(api, tmp_path):
    _, sessions, _ = api
    user = await seed_user(sessions)
    job = await make_job(sessions)
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "pipeline.md").write_text(f"- [ ] {job.canonical_url} | Acme | Director of Engineering | Remote | source: greenhouse | eligibility: uncertain | reason: re-seen\n", encoding="utf-8")

    async with sessions() as db:
        item = await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id))
        item.pipeline_status = "Evaluated"
        item.fit_score = 4.5
        item.recommendation = "Strong match"
        item.evaluated_at = utcnow()
        await db.commit()

    async with sessions() as db:
        await import_pipeline(db, user, workspace)

    async with sessions() as db:
        from sqlalchemy import select

        item2 = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == job.id))
        assert item2.pipeline_status == "Evaluated"
        assert item2.fit_score == 4.5
        assert item2.recommendation == "Strong match"


async def test_import_pipeline_still_populates_fresh_candidate_job(api, tmp_path):
    _, sessions, _ = api
    user = await seed_user(sessions)
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "pipeline.md").write_text("- [ ] https://job-boards.greenhouse.io/acme/2 | Acme | VP of Engineering | Remote | source: greenhouse | eligibility: eligible | reason: fresh find\n", encoding="utf-8")

    async with sessions() as db:
        # import_pipeline itself only flushes; callers (direct_discovery /
        # reverse_discovery / level3_all) always commit afterwards via
        # populate_candidate_jobs — mirror that here.
        jobs = await import_pipeline(db, user, workspace)
        await db.commit()

    async with sessions() as db:
        from sqlalchemy import select

        job = jobs["https://job-boards.greenhouse.io/acme/2"]
        item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == job.id))
        assert item.pipeline_status == "Inbox"
        assert item.eligibility == "eligible"
        assert item.triage_reason == "fresh find"
