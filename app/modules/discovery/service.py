import asyncio
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import SessionLocal
from app.modules.automation.runner import prepare_workspace, run_in_workspace
from app.modules.discovery.models import DiscoveryRun
from app.modules.discovery.sources import REVERSE_SCAN_SOURCES

MAX_REQUEST_COMPANIES_PER_ATS = 50
# The backend capability set for the full-network reverse-ATS scan
# (scan-ats-full.mjs). Sourced from discovery.sources' verified
# REVERSE_SCAN_SOURCES (Checkpoint B/D) rather than a locally hand-maintained
# literal, so enabling a new source here always means it was actually
# verified as reverse-scan-capable — never "just added to a UI constant".
SUPPORTED_ATS = set(REVERSE_SCAN_SOURCES)
RUN_TIMEOUT_SECONDS = 1500
ACTIVE_STATUSES = {"queued", "running"}

_tasks: set[asyncio.Task] = set()


async def create_run(db: AsyncSession, user_id: uuid.UUID, request: dict) -> DiscoveryRun:
    run = DiscoveryRun(user_id=user_id, status="queued", request=request)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> DiscoveryRun | None:
    return await db.scalar(select(DiscoveryRun).where(DiscoveryRun.id == run_id, DiscoveryRun.user_id == user_id))


async def latest_run(db: AsyncSession, user_id: uuid.UUID) -> DiscoveryRun | None:
    return await db.scalar(select(DiscoveryRun).where(DiscoveryRun.user_id == user_id).order_by(DiscoveryRun.created_at.desc()).limit(1))


async def execute_run(run_id: uuid.UUID, settings: Settings, session_factory: async_sessionmaker[AsyncSession] = SessionLocal) -> None:
    try:
        async with session_factory() as db:
            run = await db.get(DiscoveryRun, run_id)
            if run is None:
                return
            run.status = "running"
            run.started_at = datetime.now(UTC)
            await db.commit()
            request = dict(run.request or {})
            user_id = run.user_id
            workspace = await prepare_workspace(db, user_id, settings)

        since_days = int(request.get("since_days") or 7)
        ats = [item for item in request.get("ats") or [] if item in SUPPORTED_ATS]
        limit = min(int(request.get("limit_per_ats") or MAX_REQUEST_COMPANIES_PER_ATS), MAX_REQUEST_COMPANIES_PER_ATS)

        status = "failed"
        result = None
        error = None
        try:
            completed = await run_in_workspace(workspace, settings, "scan-ats-full.mjs", "--dry-run", "--json", "--since", str(since_days), "--ats", ",".join(ats), "--limit", str(limit), timeout=RUN_TIMEOUT_SECONDS)
            if completed.returncode:
                error = completed.stderr[-2000:] or "discovery failed"
            else:
                try:
                    result = json.loads(completed.stdout)
                    status = "succeeded"
                except json.JSONDecodeError:
                    error = "scanner returned invalid JSON"
        except TimeoutError:
            error = "discovery timed out"
        except Exception as exc:
            error = repr(exc)[:2000]

        async with session_factory() as db:
            run = await db.get(DiscoveryRun, run_id)
            if run is None:
                return
            run.status = status
            run.result = result
            run.error = error
            run.finished_at = datetime.now(UTC)
            await db.commit()
    except Exception:
        try:
            async with session_factory() as db:
                run = await db.get(DiscoveryRun, run_id)
                if run is not None and run.status in ACTIVE_STATUSES:
                    run.status = "failed"
                    run.error = "discovery worker crashed"
                    run.finished_at = datetime.now(UTC)
                    await db.commit()
        except Exception:
            pass


async def fail_orphaned_runs(session_factory: async_sessionmaker[AsyncSession] = SessionLocal) -> int:
    async with session_factory() as db:
        runs = list(await db.scalars(select(DiscoveryRun).where(DiscoveryRun.status.in_(ACTIVE_STATUSES))))
        for run in runs:
            run.status = "failed"
            run.error = "discovery interrupted by API restart; run it again"
            run.finished_at = datetime.now(UTC)
        await db.commit()
        return len(runs)


def start_run_task(run_id: uuid.UUID, settings: Settings) -> asyncio.Task:
    task = asyncio.create_task(execute_run(run_id, settings))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task
