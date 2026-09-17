import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.automation.runner import run_for_candidate
from app.modules.candidates.models import User
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import upsert_job
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job

router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryRequest(BaseModel):
    since_days: int = Field(default=7, ge=1, le=30)
    ats: list[str] = Field(default_factory=lambda: ["greenhouse", "lever", "ashby", "workday"])
    limit_per_ats: int = Field(default=150, ge=1, le=1500)


class AddOffersRequest(BaseModel):
    offers: list[dict[str, Any]]


@router.post("/reverse-ats")
async def reverse_ats(payload: DiscoveryRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    allowed = [ats for ats in payload.ats if ats in {"greenhouse", "lever", "ashby", "workday"}]
    if not allowed:
        raise HTTPException(status_code=400, detail="no supported ATS selected")
    result = await run_for_candidate(db, user.id, settings, "scan-ats-full.mjs", "--dry-run", "--json", "--since", str(payload.since_days), "--ats", ",".join(allowed), "--limit", str(payload.limit_per_ats), timeout=300)
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr or "discovery failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=502, detail="scanner returned invalid JSON") from error


@router.post("/offers")
async def add_offers(payload: AddOffersRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    added = 0
    for value in payload.offers[:100]:
        try:
            offer = JobIngest(company=str(value["company"]), title=str(value["title"]), location=str(value.get("location") or ""), source=str(value.get("source") or value.get("ats") or "web-discovery"), posting_url=str(value["url"]), direct_application_url=str(value["url"]), posted_at=value.get("postedAt"), source_metadata=value)
        except (KeyError, ValueError):
            continue
        job, _ = await upsert_job(db, offer)
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added from candidate discovery; awaiting cheap triage"))
        added += 1
    return {"added": added}
