"""Regression coverage for the production bug found in the first controlled
morning run: a long-running ATS scan subprocess (up to 30 min) held a DB
connection checked out (never returned to the pool) for its entire
duration, so pool_pre_ping never got a chance to test/refresh it before the
next query — surfacing as a raw asyncpg InterfaceError that crashed the
rest of the run. Fixed in automation.runner.run_for_candidate (db.close()
right after the only DB read it needs, before the subprocess wait).
"""

import json
import uuid

from app.modules.automation import batch as automation_batch
from app.modules.automation import workspace as workspace_module
from app.modules.automation.runner import CommandResult
from app.modules.candidates.models import CandidateProfile, User
from app.modules.discovery.ats_rotation import get_or_create_cursor


def use_fake_workspace_layer(monkeypatch):
    """Real run_for_candidate calls materialize_profile -> ensure_system_layer,
    which symlinks a real providers/scan.mjs tree — irrelevant to what these
    tests exercise (session/connection handling around the subprocess call),
    same fake used by test_watchlist_scan.py."""

    def fake_ensure_system_layer(workspace, settings):
        (workspace / "data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(workspace_module, "ensure_system_layer", fake_ensure_system_layer)


async def seed_user_and_profile(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, portals_yaml="title_filter:\n  positive: []\n  negative: []\ntracked_companies: []\n"))
        await db.commit()
        return user


async def test_run_for_candidate_closes_the_session_before_the_subprocess_wait(api, monkeypatch):
    """The exact fix: db.close() must happen BEFORE run_in_workspace's
    (potentially very long) subprocess wait, not after — otherwise the
    connection is still pinned for the whole duration, defeating the point."""
    _, sessions, settings = api
    user = await seed_user_and_profile(sessions)
    use_fake_workspace_layer(monkeypatch)

    call_order = []

    async def fake_run_in_workspace(workspace, settings, script, *args, timeout=900):
        call_order.append("run_in_workspace")
        return CommandResult(0, "{}", "")

    from app.modules.automation import runner as runner_module

    monkeypatch.setattr(runner_module, "run_in_workspace", fake_run_in_workspace)

    async with sessions() as db:
        original_close = db.close
        closed_before_subprocess = {"value": False}

        async def tracking_close():
            if "run_in_workspace" not in call_order:
                closed_before_subprocess["value"] = True
            await original_close()

        db.close = tracking_close
        await runner_module.run_for_candidate(db, user.id, settings, "scan-ats-full.mjs", "--since", "7", timeout=900)

    assert closed_before_subprocess["value"] is True


async def test_session_is_usable_again_immediately_after_run_for_candidate(api, monkeypatch):
    """Confirms the caller's session isn't left broken — the next query
    after run_for_candidate returns must work normally (a fresh connection
    is transparently acquired)."""
    _, sessions, settings = api
    user = await seed_user_and_profile(sessions)
    use_fake_workspace_layer(monkeypatch)

    from app.modules.automation import runner as runner_module

    async def fake_run_in_workspace(workspace, settings, script, *args, timeout=900):
        return CommandResult(0, "{}", "")

    monkeypatch.setattr(runner_module, "run_in_workspace", fake_run_in_workspace)

    async with sessions() as db:
        await runner_module.run_for_candidate(db, user.id, settings, "scan-ats-full.mjs", "--since", "7", timeout=900)
        # The session must still be perfectly usable — this is the "revalidate
        # a fresh connection after the subprocess" requirement.
        refreshed = await db.get(User, user.id)
        assert refreshed is not None
        assert refreshed.clerk_user_id == "clerk-a"


async def fake_run_for_candidate_ok(db, user_id, settings, script, *args, timeout=900):
    ats = args[args.index("--ats") + 1] if "--ats" in args else "unknown"
    return CommandResult(0, json.dumps({"datasetSize": {ats: 1000}}), "")


async def test_scan_failure_leaves_the_cursor_unchanged(api, monkeypatch):
    """Discovery itself failing (non-zero returncode, e.g. the liveness
    Playwright error observed in production) must not advance the cursor —
    the existing, correct behavior this fix must preserve."""
    _, sessions, settings = api
    await seed_user_and_profile(sessions)

    async def fake_run_failing(db, user_id, settings, script, *args, timeout=900):
        return CommandResult(1, "", "Fatal: browserType.launch: Executable doesn't exist")

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_failing)

    async with sessions() as db:
        result = await automation_batch.rotating_reverse_discovery(db, settings, "ashby", batch_size=500)
    assert result["status"] == "error"
    assert result["next_offset"] == 0

    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "ashby")
    assert cursor.next_offset == 0
    assert cursor.last_status == "error"


async def test_persistence_failure_after_a_successful_scan_leaves_the_cursor_unchanged(api, monkeypatch):
    """Discovery SUCCEEDS (returncode 0) but persisting the results
    (import_pipeline) raises — the cursor must still not advance, since
    advance_cursor is only ever reached after that succeeds too."""
    _, sessions, settings = api
    await seed_user_and_profile(sessions)
    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)

    async def fake_import_pipeline_raises(db, user, workspace, method=None, default_source=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(automation_batch, "import_pipeline", fake_import_pipeline_raises)

    async with sessions() as db:
        raised = False
        try:
            await automation_batch.rotating_reverse_discovery(db, settings, "lever", batch_size=1500)
        except RuntimeError:
            raised = True
    assert raised  # propagates uncaught — morning_run's own isolation catches it

    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "lever")
    assert cursor.next_offset == 0  # advance_cursor was never reached


async def test_successful_complete_scan_advances_the_cursor(api, monkeypatch):
    _, sessions, settings = api
    await seed_user_and_profile(sessions)
    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)

    async with sessions() as db:
        result = await automation_batch.rotating_reverse_discovery(db, settings, "greenhouse", batch_size=1500)
    assert result["status"] == "ok"
    # dataset_size (1000, from the fake's datasetSize payload) wraps: (0 + 1500) % 1000 = 500
    assert result["next_offset"] == 500

    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "greenhouse")
    assert cursor.next_offset == 500


async def test_one_ats_failure_does_not_prevent_subsequent_providers_or_candidates(api, monkeypatch):
    """End-to-end via morning_run: a DB-poisoning-style failure on one
    provider (simulated by raising a real exception mid-way through its
    persistence step, same shape as the production bug) must not prevent
    the remaining providers or the per-candidate cycle from running."""
    _, sessions, settings = api
    user = await seed_user_and_profile(sessions)

    async def fake_watchlist_all(db, settings):
        return {"targets": 0}

    async def flaky_for_workday(db, user_id, settings, script, *args, timeout=900):
        if "--ats" in args and args[args.index("--ats") + 1] == "workday":
            raise RuntimeError("cannot call PreparedStatement.fetch(): the underlying connection is closed")
        return await fake_run_for_candidate_ok(db, user_id, settings, script, *args, timeout=timeout)

    monkeypatch.setattr(automation_batch, "run_for_candidate", flaky_for_workday)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)

    async with sessions() as db:
        result = await automation_batch.morning_run(db, settings, disable_ai=True)

    assert result["status"] == "completed_with_warnings"
    assert result["summary"]["sources"]["workday"]["status"] == "error"
    for ats in ("ashby", "greenhouse", "icims", "lever"):
        assert result["summary"]["sources"][ats]["status"] == "ok"
    candidate_result = result["summary"]["candidates"][str(user.id)]
    assert candidate_result["ai_status"] == "disabled_for_controlled_run"  # candidate cycle still ran fully
