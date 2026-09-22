"""scan.mjs's pipeline.md writer carries no per-row `source:` label, so
import_pipeline's caller must supply one when it's actually known
(Checkpoint E finding, fixed alongside the UI work that surfaces per-ATS
metrics). reverse_discovery knows its single `ats` per call; verify Job/
JobDiscovery end up correctly attributed instead of "legacy-pipeline".
"""

import uuid

from sqlalchemy import select

from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job, JobDiscovery
from app.modules.migration.service import import_pipeline


async def seed_user(sessions) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id="clerk-src", email="src@example.com", name="src")
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, portals_yaml="tracked_companies: []\n"))
        await db.commit()
        return user


async def test_import_pipeline_uses_explicit_default_source_when_row_has_none(api, tmp_path):
    _, sessions, _ = api
    user = await seed_user(sessions)
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    # A realistic scan.mjs/scan-ats-full.mjs row: no `source:` label at all.
    (workspace / "data" / "pipeline.md").write_text("- [ ] https://job-boards.greenhouse.io/acme/1 | Acme | Director of Engineering | Remote\n", encoding="utf-8")

    async with sessions() as db:
        await import_pipeline(db, user, workspace, method="reverse_ats", default_source="greenhouse")
        await db.commit()

    async with sessions() as db:
        job = await db.scalar(select(Job))
        assert job.source == "greenhouse"
        discovery = await db.scalar(select(JobDiscovery).where(JobDiscovery.job_id == job.id))
        assert discovery.source == "greenhouse"
        assert discovery.method == "reverse_ats"


async def test_import_pipeline_falls_back_to_legacy_pipeline_without_a_hint(api, tmp_path):
    _, sessions, _ = api
    user = await seed_user(sessions)
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "pipeline.md").write_text("- [ ] https://job-boards.greenhouse.io/acme/2 | Acme | VP of Engineering | Remote\n", encoding="utf-8")

    async with sessions() as db:
        await import_pipeline(db, user, workspace)  # no default_source given
        await db.commit()

    async with sessions() as db:
        job = await db.scalar(select(Job))
        assert job.source == "legacy-pipeline"
