import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.automation import scheduler
from app.modules.automation.scheduler import morning_run_in_progress, morning_sweep_loop, parse_schedule, reap_stale_morning_runs, run_sweep_once, seconds_until
from app.modules.discovery.models import MorningRun


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 5, hour, minute, tzinfo=timezone.utc)


async def seed_morning_run(sessions, *, status: str, started_at: datetime) -> MorningRun:
    async with sessions() as db:
        run = MorningRun(id=uuid.uuid4(), status=status, started_at=started_at)
        db.add(run)
        await db.commit()
        return run


def test_seconds_until_later_today():
    assert seconds_until(10, 30, dt(10, 0)) == 1800


def test_seconds_until_earlier_today_wraps_to_tomorrow():
    assert seconds_until(9, 30, dt(10, 0)) == 84600


def test_seconds_until_exactly_now_is_tomorrow():
    assert seconds_until(10, 0, dt(10, 0)) == 86400


def test_parse_schedule_valid():
    assert parse_schedule("03:30") == (3, 30)


def test_parse_schedule_empty_is_disabled():
    assert parse_schedule("") is None


def test_parse_schedule_out_of_range(caplog):
    assert parse_schedule("25:00") is None


def test_parse_schedule_junk(caplog):
    assert parse_schedule("junk") is None


async def test_reap_stale_morning_runs(api):
    _, sessions, _ = api
    now = datetime.now(timezone.utc)
    stale = await seed_morning_run(sessions, status="running", started_at=now - timedelta(hours=4))
    fresh = await seed_morning_run(sessions, status="running", started_at=now - timedelta(minutes=10))

    async with sessions() as db:
        assert await reap_stale_morning_runs(db) == 1

    async with sessions() as db:
        stale_row = await db.get(MorningRun, stale.id)
        fresh_row = await db.get(MorningRun, fresh.id)
    assert stale_row.status == "failed"
    assert "orphaned" in stale_row.summary["error"]
    assert stale_row.finished_at is not None
    assert fresh_row.status == "running"


async def test_run_sweep_once_skips_when_run_in_progress(api):
    _, sessions, settings = api
    await seed_morning_run(sessions, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    calls = []

    async def fake_runner(db, settings_, *, disable_ai):
        calls.append(disable_ai)
        return {"status": "completed"}

    result = await run_sweep_once(settings, session_factory=sessions, runner=fake_runner)
    assert result["status"] == "skipped"
    assert calls == []


async def test_run_sweep_once_runs_zero_token_by_default(api):
    _, sessions, settings = api
    calls = []

    async def fake_runner(db, settings_, *, disable_ai):
        calls.append(disable_ai)
        return {"status": "completed"}

    result = await run_sweep_once(settings, session_factory=sessions, runner=fake_runner)
    assert result["status"] == "completed"
    assert calls == [True]


async def test_run_sweep_once_ai_enabled(api):
    _, sessions, settings = api
    settings.morning_sweep_ai = True
    calls = []

    async def fake_runner(db, settings_, *, disable_ai):
        calls.append(disable_ai)
        return {"status": "completed"}

    await run_sweep_once(settings, session_factory=sessions, runner=fake_runner)
    assert calls == [False]


async def test_morning_run_in_progress_ignores_stale(api):
    _, sessions, _ = api
    await seed_morning_run(sessions, status="running", started_at=datetime.now(timezone.utc) - timedelta(hours=5))
    async with sessions() as db:
        assert await morning_run_in_progress(db) is False


async def test_sweep_loop_sleeps_then_runs_then_propagates_cancel(api):
    _, sessions, settings = api
    settings.morning_sweep_schedule_utc = "10:30"
    sleeps = []
    runs = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError()

    async def fake_run_once(settings_):
        runs.append(settings_)
        return {"status": "completed"}

    with pytest.raises(asyncio.CancelledError):
        await morning_sweep_loop(settings, sleep=fake_sleep, now=lambda: dt(10, 0), run_once=fake_run_once)

    assert sleeps[0] == seconds_until(10, 30, dt(10, 0)) == 1800
    assert len(runs) == 1


async def test_sweep_loop_disabled_returns_immediately(api):
    _, sessions, settings = api
    settings.morning_sweep_schedule_utc = ""
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    await morning_sweep_loop(settings, sleep=fake_sleep, now=lambda: dt(10, 0), run_once=None)
    assert sleeps == []
