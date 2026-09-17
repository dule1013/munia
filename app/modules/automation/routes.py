import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.automation.runner import run_for_candidate
from app.modules.automation.service import evaluate, generate_cv, resolve_candidate_job
from app.modules.candidates.models import User

router = APIRouter(prefix="/career-ops", tags=["career-ops"])


class RunRequest(BaseModel):
    kind: str
    input: str
    confirm_manual_overwrite: bool = False


@router.post("/verify")
async def verify_candidate(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    result = await run_for_candidate(db, user.id, settings, "verify-pipeline.mjs", "--summary", timeout=180)
    if result.returncode:
        raise HTTPException(status_code=422, detail=result.stderr or result.stdout)
    return {"ok": True, "output": result.stdout}


@router.post("/run")
async def run(payload: RunRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    resolved = await resolve_candidate_job(db, user.id, payload.input)
    if not resolved:
        raise HTTPException(status_code=404, detail="candidate job not found")
    item, job = resolved
    if payload.kind not in {"evaluate", "pdf"}:
        raise HTTPException(status_code=400, detail="unsupported run kind")

    async def events():
        yield b'{"type":"status","label":"Starting isolated Career Ops workspace..."}\n'
        operation = evaluate(db, item, job, settings) if payload.kind == "evaluate" else generate_cv(db, item, job, settings, payload.confirm_manual_overwrite)
        task = asyncio.create_task(operation)
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except TimeoutError:
                yield b'{"type":"keepalive"}\n'
        try:
            text = await task
            if text:
                yield (json_line({"type": "text", "text": text + "\n"}))
            yield b'{"type":"done","tokens":0}\n'
        except PermissionError as error:
            yield json_line({"type": "error", "msg": str(error), "code": "manual-cv-overwrite-confirmation-required"})
        except (ValueError, RuntimeError) as error:
            yield json_line({"type": "error", "msg": str(error)})

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


def json_line(value: dict) -> bytes:
    import json
    return (json.dumps(value) + "\n").encode()
