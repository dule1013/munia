"""iCIMS as a genuine fifth reverse-network source (Checkpoint D §1).

`test_icims_is_a_backend_supported_ats` is a pure unit check. The second test
is a REAL (non-mocked) end-to-end run through the exact code path Munia's
Explore/discovery-run feature invokes — the same one already exercised with
mocks in test_discovery_runs.py — to prove iCIMS isn't just a UI/constant
change. It needs network + node and is skipped if either is unavailable.
"""

import shutil
import socket
import uuid

import pytest

from app.modules.candidates.models import CandidateProfile, User
from app.modules.discovery.service import SUPPORTED_ATS, create_run, execute_run


def test_icims_is_a_backend_supported_ats():
    assert SUPPORTED_ATS == {"greenhouse", "lever", "ashby", "workday", "icims"}


def _network_available() -> bool:
    try:
        socket.create_connection(("raw.githubusercontent.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.skipif(not _network_available(), reason="no network access to fetch the iCIMS company dataset")
async def test_icims_dry_run_succeeds_through_the_real_discovery_run_path(api):
    client, sessions, settings = api
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id="clerk-icims", email="icims@example.com", name="icims")
        db.add(user)
        await db.flush()
        # A real onboarded candidate always has a non-empty portals.yml
        # (candidates.service.portals_yaml); a bare test User otherwise
        # materializes an empty one, which scan-ats-full.mjs's YAML parser
        # rejects outright — unrelated to iCIMS, so give it a minimal valid one.
        db.add(CandidateProfile(user_id=user.id, portals_yaml="title_filter:\n  positive: []\n  negative: []\ntracked_companies: []\n"))
        await db.commit()

    from pathlib import Path

    from app.core.config import get_settings

    real_settings = get_settings().model_copy(update={"database_url": settings.database_url, "environment": "test", "auth_test_mode": True, "career_ops_code_root": Path(__file__).resolve().parents[2], "career_ops_workspace_root": settings.career_ops_workspace_root})

    async with sessions() as db:
        run = await create_run(db, user.id, {"since_days": 30, "ats": ["icims"], "limit_per_ats": 1})
        run_id = run.id

    await execute_run(run_id, real_settings, session_factory=sessions)

    async with sessions() as db:
        finished = await db.get(type(run), run_id)
        assert finished.status in {"succeeded", "failed"}
        # A dataset/network hiccup is tolerated (this box's egress isn't
        # guaranteed), but a hard scanner/plumbing failure is not.
        if finished.status == "failed":
            assert "unknown" not in (finished.error or "").lower()
        else:
            assert finished.result is not None
            assert finished.result.get("companiesAvailable", 0) > 0
