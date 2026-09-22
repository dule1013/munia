"""Verifies Level-3 web discovery (run_multi_user_automation.py level3) still
flows through the Checkpoint B ingest_discovery() path and records
method=web_search, per Checkpoint D §7. Level-3 itself (the `claude` CLI
agent call) is mocked — this test is about the JobDiscovery wiring around
it, not about re-running a real LLM.
"""

import uuid

from sqlalchemy import select

from app.modules.automation import batch
from app.modules.automation.runner import CommandResult
from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job, JobDiscovery


async def seed_user(sessions) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id="clerk-l3", email="l3@example.com", name="l3")
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, portals_yaml="tracked_companies: []\n"))
        await db.commit()
        return user


async def test_level3_all_records_web_search_discoveries(api, monkeypatch, tmp_path):
    _, sessions, settings = api
    user = await seed_user(sessions)

    workspace = settings.career_ops_workspace_root / str(user.id)
    (workspace / "data").mkdir(parents=True, exist_ok=True)
    (workspace / "data" / "pipeline.md").write_text("- [ ] https://jobs.ashbyhq.com/acme/1 | Acme | Director of Engineering | Remote\n", encoding="utf-8")

    async def fake_run_agent(db, user_id, settings_, prompt, model):
        return CommandResult(0, "", "")

    monkeypatch.setattr(batch, "_run_agent", fake_run_agent)

    async with sessions() as db:
        result = await batch.level3_all(db, settings)

    assert result["completed"] == 1

    async with sessions() as db:
        job = await db.scalar(select(Job))
        assert job is not None
        discovery = await db.scalar(select(JobDiscovery).where(JobDiscovery.job_id == job.id))
        assert discovery.method == "web_search"
