import uuid

import pytest
from sqlalchemy import select

from app.modules.artifacts.models import TailoredCv
from app.modules.automation.batch import persist_triage_results
from app.modules.automation.service import manual_overwrite_required
from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob


def test_manual_tailored_cv_requires_explicit_ai_overwrite():
    cv = TailoredCv(id=uuid.uuid4(), user_id=uuid.uuid4(), job_id=uuid.uuid4(), source_html="<html></html>", manually_edited=True, validation_status="valid")
    assert manual_overwrite_required(cv, False)
    assert not manual_overwrite_required(cv, True)
    cv.manually_edited = False
    assert not manual_overwrite_required(cv, False)


async def triage_fixture(sessions):
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id="triage-user", email="triage@example.com", name="Triage User")
        jobs = [
            Job(id=uuid.uuid4(), canonical_key=f"key-{index}", canonical_url=f"https://jobs.example.com/{index}", company=f"Company {index}", title=f"Role {index}", location="Remote", source="greenhouse", posting_url=f"https://jobs.example.com/{index}", source_metadata={})
            for index in range(3)
        ]
        db.add_all([user, *jobs])
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, profile={}, master_cv="# CV", profile_yaml="", profile_markdown="", cv_facts={}))
        items = [CandidateJob(id=uuid.uuid4(), user_id=user.id, job_id=job.id, pipeline_status="Inbox", triage_result="uncertain", triage_reason="pending") for job in jobs]
        db.add_all(items)
        await db.commit()
        return user, jobs, items


async def test_canonical_shortlist_is_persisted_transactionally(api):
    _, sessions, settings = api
    user, jobs, _ = await triage_fixture(sessions)
    data = settings.career_ops_workspace_root / str(user.id) / "data"
    data.mkdir(parents=True)
    data.joinpath("pipeline.md").write_text(
        f"- [ ] {jobs[0].posting_url} | Company 0 | Role 0 | Remote\n"
        f"- [ ] {jobs[1].posting_url} | Company 1 | Role 1 | Madrid\n"
        f"- [x] {jobs[2].posting_url} | Company 2 | Role 2 | London | source: lever | eligibility: ineligible | reason: UK-only | liveness: active\n"
    )
    data.joinpath("shortlist.md").write_text(
        "## Worth evaluating\n"
        "### Company 0 — Role 0\n"
        f"- Location: Remote\n- Posted: 2026-09-15\n- Source: greenhouse\n- Eligibility: eligible\n- Why it may fit: Multi-team leadership\n- Direct application URL: {jobs[0].posting_url}\n"
        "## Uncertain\n"
        f"Company 1, Role 1, Madrid, 2026-09-14, lever, {jobs[1].posting_url}, needs verification, Scope requires JD review\n"
    )
    async with sessions() as db:
        assert await persist_triage_results(db, user.id, data.parent) == 3
        rows = list(await db.scalars(select(CandidateJob).where(CandidateJob.user_id == user.id).order_by(CandidateJob.created_at)))
        by_job = {row.job_id: row for row in rows}
        worth = by_job[jobs[0].id]
        uncertain = by_job[jobs[1].id]
        discard = by_job[jobs[2].id]
        assert (worth.triage_result, worth.eligibility, worth.triage_reason) == ("worth", "eligible", "Multi-team leadership")
        assert worth.triage_metadata["source"] == "greenhouse"
        assert (uncertain.triage_result, uncertain.eligibility, uncertain.triage_reason) == ("uncertain", "needs verification", "Scope requires JD review")
        assert uncertain.triage_metadata["location"] == "Madrid"
        assert (discard.triage_result, discard.pipeline_status, discard.skipped) == ("discard", "Discarded", True)
        assert discard.triage_reason == "UK-only"
        assert discard.triage_metadata["liveness"] == "active"


async def test_malformed_shortlist_rolls_back_without_discarding_jobs(api):
    _, sessions, settings = api
    user, jobs, _ = await triage_fixture(sessions)
    data = settings.career_ops_workspace_root / str(user.id) / "data"
    data.mkdir(parents=True)
    data.joinpath("pipeline.md").write_text(f"- [x] {jobs[0].posting_url} | Company 0 | Role 0 | reason: should not persist\n")
    data.joinpath("shortlist.md").write_text("## Unexpected agent output\n")
    async with sessions() as db:
        with pytest.raises(ValueError, match="canonical triage sections"):
            await persist_triage_results(db, user.id, data.parent)
        item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == jobs[0].id))
        assert (item.pipeline_status, item.triage_reason) == ("Inbox", "pending")
