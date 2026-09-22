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
    workspace = await prepare_workspace(db, user_id, settings)
    return await run_in_workspace(workspace, settings, script, *arguments, timeout=timeout)
