import json
import uuid

from app.core.database import Base
from app.modules.automation import batch as automation_batch
from app.modules.automation.runner import CommandResult
from app.modules.candidates.models import CandidateProfile, User
from app.modules.discovery.ats_rotation import advance_cursor, get_or_create_cursor, next_batch
from app.modules.discovery.models import AtsScanCursor


async def seed_user_and_profile(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, portals_yaml="title_filter:\n  positive: []\n  negative: []\ntracked_companies: []\n"))
        await db.commit()
        return user


def test_next_batch_returns_current_offset_and_batch_size_without_mutating():
    cursor = AtsScanCursor(id=uuid.uuid4(), source="greenhouse", next_offset=1500)
    offset, limit = next_batch(cursor, 1500)
    assert (offset, limit) == (1500, 1500)
    assert cursor.next_offset == 1500  # pure — unchanged until advance_cursor


async def test_cursor_created_once_and_persisted(api):
    _, sessions, _ = api
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "greenhouse")
        await db.commit()
        first_id = cursor.id
    async with sessions() as db:
        cursor2 = await get_or_create_cursor(db, "greenhouse")
    assert cursor2.id == first_id
    assert cursor2.next_offset == 0


async def test_each_provider_has_an_independent_cursor(api):
    _, sessions, _ = api
    async with sessions() as db:
        gh = await get_or_create_cursor(db, "greenhouse")
        await advance_cursor(db, gh, scanned_offset=0, batch_size=1500, dataset_size=8333, status="ok")
        lever = await get_or_create_cursor(db, "lever")
        await db.commit()
    async with sessions() as db:
        gh2 = await get_or_create_cursor(db, "greenhouse")
        lever2 = await get_or_create_cursor(db, "lever")
    assert gh2.next_offset == 1500
    assert lever2.next_offset == 0


async def test_deterministic_progression_across_runs(api):
    _, sessions, _ = api
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "ashby")
        await advance_cursor(db, cursor, scanned_offset=0, batch_size=500, dataset_size=3161, status="ok")
        await db.commit()
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "ashby")
        assert cursor.next_offset == 500
        await advance_cursor(db, cursor, scanned_offset=500, batch_size=500, dataset_size=3161, status="ok")
        await db.commit()
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "ashby")
        assert cursor.next_offset == 1000


async def test_wraparound_when_offset_plus_batch_reaches_dataset_end(api):
    _, sessions, _ = api
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "icims")
        await advance_cursor(db, cursor, scanned_offset=9700, batch_size=700, dataset_size=10108, status="ok")
        await db.commit()
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "icims")
        assert cursor.next_offset == (9700 + 700) % 10108


async def test_failed_scan_does_not_advance_the_cursor(api):
    _, sessions, _ = api
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "workday")
        await advance_cursor(db, cursor, scanned_offset=0, batch_size=100, dataset_size=5000, status="ok")
        await db.commit()
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "workday")
        assert cursor.next_offset == 100
        await advance_cursor(db, cursor, scanned_offset=100, batch_size=100, dataset_size=5000, status="error", error="timeout")
        await db.commit()
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "workday")
        assert cursor.next_offset == 100  # unchanged — the failed slice is retried, not skipped
        assert cursor.last_status == "error"
        assert cursor.last_error == "timeout"


async def test_dataset_size_change_is_tolerated_via_modulo(api):
    """The dataset shrank since the cursor was saved — advance_cursor must
    not crash or produce a nonsensical offset."""
    _, sessions, _ = api
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "greenhouse")
        cursor.next_offset = 9000
        await db.commit()
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "greenhouse")
        await advance_cursor(db, cursor, scanned_offset=9000, batch_size=1500, dataset_size=8333, status="ok")
        await db.commit()
    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "greenhouse")
        assert 0 <= cursor.next_offset < 8333


async def test_rotating_reverse_discovery_advances_cursor_on_success(api, monkeypatch):
    _, sessions, settings = api
    await seed_user_and_profile(sessions)

    async def fake_run_for_candidate(db, user_id, settings, script, *args, timeout=900):
        return CommandResult(0, json.dumps({"datasetSize": {"greenhouse": 8333}}), "")

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate)

    async with sessions() as db:
        result = await automation_batch.rotating_reverse_discovery(db, settings, "greenhouse", batch_size=1500)
    assert result["status"] == "ok"
    assert result["offset"] == 0
    assert result["next_offset"] == 1500
    assert result["dataset_size"] == 8333

    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "greenhouse")
    assert cursor.next_offset == 1500


async def test_rotating_reverse_discovery_does_not_advance_on_failure(api, monkeypatch):
    _, sessions, settings = api
    await seed_user_and_profile(sessions)

    async def fake_run_for_candidate(db, user_id, settings, script, *args, timeout=900):
        return CommandResult(1, "", "network error")

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate)

    async with sessions() as db:
        result = await automation_batch.rotating_reverse_discovery(db, settings, "lever", batch_size=1500)
    assert result["status"] == "error"
    assert result["next_offset"] == 0

    async with sessions() as db:
        cursor = await get_or_create_cursor(db, "lever")
    assert cursor.next_offset == 0
    assert cursor.last_status == "error"


async def test_all_five_reverse_ats_providers_can_participate_in_one_morning_cycle(api, monkeypatch):
    _, sessions, settings = api
    await seed_user_and_profile(sessions)

    async def fake_run_for_candidate(db, user_id, settings, script, *args, timeout=900):
        ats = args[args.index("--ats") + 1]
        return CommandResult(0, json.dumps({"datasetSize": {ats: 1000}}), "")

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate)

    results = {}
    for ats in ("greenhouse", "lever", "ashby", "workday", "icims"):
        async with sessions() as db:
            results[ats] = await automation_batch.rotating_reverse_discovery(db, settings, ats, batch_size=100)

    assert all(r["status"] == "ok" for r in results.values())
    async with sessions() as db:
        for ats in results:
            cursor = await get_or_create_cursor(db, ats)
            assert cursor.next_offset == 100  # each advanced independently


async def test_manual_reverse_discovery_still_uses_shuffle_not_offset(api, monkeypatch):
    """reverse_discovery (used by manual `run_multi_user_automation.py <ats>`
    and unrelated to the new rotation path) must keep its existing
    --shuffle behavior untouched."""
    _, sessions, settings = api
    await seed_user_and_profile(sessions)
    seen_args = []

    async def fake_run_for_candidate(db, user_id, settings, script, *args, timeout=900):
        seen_args.extend(args)
        return CommandResult(0, "", "")

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate)
    async with sessions() as db:
        await automation_batch.reverse_discovery(db, settings, "greenhouse", 1500)
    assert "--shuffle" in seen_args
    assert "--offset" not in seen_args
