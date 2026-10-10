"""In-process nightly morning sweep (no separate Railway service — the api
service owns the /data volume CAREER_OPS_WORKSPACE_ROOT lives on, so the
sweep must run here).

Enabled by Settings.morning_sweep_schedule_utc ("HH:MM", 24h UTC; empty =
off). Zero-token by default: the sweep calls morning_run(disable_ai=True)
unless Settings.morning_sweep_ai is on.

Also owns the stale-MorningRun reaper: a "running" MorningRun with no
heartbeat past STALE_RUN_AFTER means the api restarted mid-run, so it is
marked failed instead of blocking every future sweep forever.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import SessionLocal
from app.modules.discovery.models import MorningRun

logger = logging.getLogger(__name__)

STALE_RUN_AFTER = timedelta(hours=3)


def parse_schedule(value: str) -> tuple[int, int] | None:
    """"HH:MM" (24h UTC) → (hour, minute); None for empty/invalid."""
    value = (value or "").strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 2:
        logger.warning("invalid morning_sweep_schedule_utc %r (expected HH:MM) — scheduler disabled", value)
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        logger.warning("invalid morning_sweep_schedule_utc %r (expected HH:MM) — scheduler disabled", value)
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        logger.warning("invalid morning_sweep_schedule_utc %r (expected HH:MM) — scheduler disabled", value)
        return None
    return hour, minute


def seconds_until(hour: int, minute: int, now: datetime) -> float:
    """Seconds to the next occurrence of hour:minute UTC strictly after `now`
    (at or past it today → tomorrow). Pure."""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def reap_stale_morning_runs(db: AsyncSession) -> int:
    """Fail "running" MorningRuns whose started_at is older than
    STALE_RUN_AFTER — an api restart/crash leaves them orphaned forever
    otherwise. Returns the number reaped."""
    cutoff = datetime.now(timezone.utc) - STALE_RUN_AFTER
    stale = list(await db.scalars(select(MorningRun).where(MorningRun.status == "running", MorningRun.started_at < cutoff)))
    now = datetime.now(timezone.utc)
    for run in stale:
        run.status = "failed"
        run.summary = {**(run.summary or {}), "error": "orphaned: no heartbeat (api restart or crash)"}
        run.finished_at = now
    if stale:
        await db.commit()
    return len(stale)


async def morning_run_in_progress(db: AsyncSession) -> bool:
    """A "running" MorningRun started within STALE_RUN_AFTER still counts as
    live; older ones are stale orphans (see reap_stale_morning_runs)."""
    cutoff = datetime.now(timezone.utc) - STALE_RUN_AFTER
    return await db.scalar(select(MorningRun.id).where(MorningRun.status == "running", MorningRun.started_at >= cutoff).limit(1)) is not None


async def run_sweep_once(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    runner=None,
) -> dict:
    """One sweep: reap stale runs, skip if one is already in progress,
    otherwise run the morning cycle. Never raises — a sweep failure is
    logged and reported, not propagated into the scheduler loop."""
    if runner is None:
        # Lazy import: batch.py pulls in most of the app; importing it at
        # module top would couple scheduler startup (and its tests) to that
        # whole graph and risks a circular-import surprise.
        from app.modules.automation.batch import morning_run as runner
    async with session_factory() as db:
        reaped = await reap_stale_morning_runs(db)
        if reaped:
            logger.warning("reaped %d stale morning run(s) before sweep", reaped)
        if await morning_run_in_progress(db):
            return {"status": "skipped", "reason": "run in progress"}
        try:
            return await runner(db, settings, disable_ai=not settings.morning_sweep_ai)
        except Exception as error:
            logger.exception("morning sweep failed")
            return {"status": "error", "error": str(error)[:500]}


async def morning_sweep_loop(
    settings: Settings,
    *,
    sleep=asyncio.sleep,
    now=lambda: datetime.now(timezone.utc),
    run_once=run_sweep_once,
) -> None:
    """Sleep until each scheduled UTC time, then run one sweep — forever.
    Returns immediately when no valid schedule is configured. CancelledError
    propagates so lifespan shutdown stops the loop cleanly."""
    schedule = parse_schedule(settings.morning_sweep_schedule_utc)
    if schedule is None:
        return
    hour, minute = schedule
    while True:
        await sleep(seconds_until(hour, minute, now()))
        logger.info("morning sweep starting")
        result = await run_once(settings)
        logger.info("morning sweep finished: %s", result.get("status"))
