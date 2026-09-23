import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.automation.workspace import candidate_environment, materialize_profile
from app.modules.candidates.service import get_profile


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


async def prepare_workspace(db: AsyncSession, user_id: uuid.UUID, settings: Settings) -> Path:
    profile = await get_profile(db, user_id)
    return await asyncio.to_thread(materialize_profile, user_id, profile, settings)


async def run_in_workspace(workspace: Path, settings: Settings, script: str, *arguments: str, timeout: int = 900) -> CommandResult:
    script_path = settings.career_ops_code_root / script
    process = await asyncio.create_subprocess_exec("node", str(script_path), *arguments, cwd=workspace, env=candidate_environment(workspace), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.terminate()
        await process.wait()
        raise
    return CommandResult(process.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"))


async def run_for_candidate(db: AsyncSession, user_id: uuid.UUID, settings: Settings, script: str, *arguments: str, timeout: int = 900) -> CommandResult:
    """The one shared boundary every long-running external scan (scan.mjs,
    scan-ats-full.mjs, ...) goes through — fixing it here fixes every
    caller (rotating_reverse_discovery, reverse_discovery, direct_discovery)
    without touching each one individually.

    `prepare_workspace` does the only DB read this function needs
    (get_profile), then returns. `db.close()` immediately after releases
    that connection back to the pool BEFORE the potentially 20+ minute
    subprocess wait in run_in_workspace, which never touches `db` at all.
    Without this, the session keeps the SAME checked-out connection pinned
    for the entire subprocess duration — never returned to the pool, so
    pool_pre_ping never gets a chance to test/refresh it on the caller's
    next query after this returns. That's exactly the failure mode observed
    in production: Neon's serverless compute can drop/suspend an
    idle-but-still-checked-out connection during a long ATS scan, and the
    caller's first post-subprocess query then fails with a raw asyncpg
    InterfaceError instead of pre_ping transparently reconnecting.

    Safe to keep using `db` after this returns: SQLAlchemy's AsyncSession
    is fully reusable after close() — the next operation just starts a new
    transaction and acquires a fresh, pre_ping-validated connection."""
    workspace = await prepare_workspace(db, user_id, settings)
    await db.close()
    return await run_in_workspace(workspace, settings, script, *arguments, timeout=timeout)
