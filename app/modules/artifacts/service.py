import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.artifacts.models import TailoredCv
from app.modules.automation.workspace import atomic_write, candidate_environment, materialize_profile
from app.modules.candidates.service import get_profile


class CvValidationError(ValueError):
    pass


class CvRenderError(RuntimeError):
    pass


async def command(*args: str, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def validate_and_render_cv(db: AsyncSession, cv: TailoredCv, source_html: str, settings: Settings) -> TailoredCv:
    profile = await get_profile(db, cv.user_id)
    workspace = await asyncio.to_thread(materialize_profile, cv.user_id, profile, settings)
    output = workspace / "output"
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / f".{cv.id}.candidate.html"
    html_path = output / f"tailored-{cv.id}.html"
    pdf_path = output / f"tailored-{cv.id}.pdf"
    await asyncio.to_thread(atomic_write, temporary, source_html)
    env = candidate_environment(workspace)
    code, stdout, stderr = await command("node", str(settings.career_ops_code_root / "verify-cv-facts.mjs"), str(temporary), cwd=workspace, env=env, timeout=180)
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    if code:
        raise CvValidationError((stdout + stderr).strip() or "CV fact validation failed")
    await asyncio.to_thread(atomic_write, html_path, source_html)
    code, stdout, stderr = await command("node", str(settings.career_ops_code_root / "generate-pdf.mjs"), str(html_path), str(pdf_path), f"--format={cv.format}", "--allow-reorder", cwd=workspace, env=env, timeout=240)
    if code or not pdf_path.is_file():
        raise CvRenderError((stdout + stderr).strip() or "PDF rendering failed")
    cv.source_html = source_html
    cv.artifact_key = str(pdf_path.relative_to(workspace))
    cv.manually_edited = True
    cv.validation_status = "valid"
    cv.validation_message = None
    await db.commit()
    await db.refresh(cv)
    return cv
