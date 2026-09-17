from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models
from app.core.config import Settings
from app.core.database import Base
from app.modules.artifacts.models import TailoredCv
from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job
from app.modules.migration.service import migrate_legacy_candidate
from app.modules.pipeline.models import CandidateJob, Evaluation


async def test_legacy_migration_is_non_destructive_and_preserves_artifacts(tmp_path):
    source = tmp_path / "legacy"
    for directory in ["config", "modes", "data", "reports", "output"]:
        (source / directory).mkdir(parents=True)
    (source / "cv.md").write_text("# CV -- Legacy Candidate\n")
    (source / "config" / "profile.yml").write_text("candidate:\n  full_name: Legacy Candidate\n  email: legacy@example.com\n")
    (source / "config" / "cv-facts.json").write_text('{"allow_metrics":[],"allow_facts":[],"forbidden_phrases":[],"warn_phrases":[]}')
    (source / "modes" / "_profile.md").write_text("# Legacy profile")
    (source / "portals.yml").write_text("title_filter:\n  positive: [Director]\n")
    url = "https://jobs.example.com/director"
    (source / "data" / "pipeline.md").write_text(f"- [ ] {url} | Shared Co | Director of Engineering | Remote\n")
    (source / "data" / "applications.md").write_text(f"| # | Date | Company | Role | Score | Status | Report | Notes |\n|---|---|---|---|---|---|---|---|\n| 1 | 2026-09-15 | Shared Co | Director of Engineering | 4.5/5 | Applied | [1](../reports/001-shared.md) | {url} |\n")
    (source / "reports" / "001-shared.md").write_text(f"# Evaluation\n\nPosting: {url}\n")
    (source / "output" / "shared.html").write_text("<html>Legacy tailored CV</html>")
    (source / "output" / "shared.pdf").write_bytes(b"pdf")
    (source / "data" / "pdf-index.tsv").write_text("1\toutput/shared.pdf\toutput/shared.html\ta4\t2026-09-15\n")

    engine = create_async_engine("sqlite+aiosqlite://")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", environment="test", auth_test_mode=True, career_ops_code_root=tmp_path / "code", career_ops_workspace_root=tmp_path / "runtime" / "users")
    async with sessions() as db:
        user, backup = await migrate_legacy_candidate(db, source, settings, "migration:legacy")
        assert await db.scalar(select(func.count()).select_from(User)) == 1
        assert await db.scalar(select(func.count()).select_from(CandidateProfile)) == 1
        assert await db.scalar(select(func.count()).select_from(Job)) == 1
        assert await db.scalar(select(func.count()).select_from(CandidateJob)) == 1
        assert await db.scalar(select(func.count()).select_from(Evaluation)) == 1
        assert await db.scalar(select(func.count()).select_from(TailoredCv)) == 1
        assert (settings.career_ops_workspace_root / str(user.id) / "output" / "shared.pdf").read_bytes() == b"pdf"
        assert (backup / "cv.md").read_text() == "# CV -- Legacy Candidate\n"
        assert (source / "cv.md").read_text() == "# CV -- Legacy Candidate\n"
    await engine.dispose()
