import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.candidates.models import User
from app.modules.discovery.models import DiscoveryRun, MorningRun
from app.modules.discovery.service import (
    ACTIVE_STATUSES,
    RUN_TIMEOUT_SECONDS,
    SUPPORTED_ATS,
    create_run,
    get_run,
    latest_run,
    start_run_task,
)
from app.modules.discovery.ai_search import AISearchNotConfigured, AISearchRateLimited, run_ai_search
from app.modules.discovery.overview import build_sources_overview
from app.modules.discovery.sources import METHOD_MANUAL, METHOD_REVERSE_ATS, METHOD_WEB_SEARCH, is_reverse_scan_capable
from app.modules.discovery.watchlist_schemas import WatchedCompanyCreate, WatchedCompanyResponse, WatchedCompanyUpdate
from app.modules.discovery.watchlist_service import create_watched_company, delete_watched_company, get_watched_company, list_watched_companies, update_watched_company
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job

router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryRequest(BaseModel):
    since_days: int = Field(default=7, ge=1, le=30)
    ats: list[str] = Field(default_factory=lambda: sorted(SUPPORTED_ATS))
    limit_per_ats: int = Field(default=150, ge=1, le=1500)


class DiscoveryRunOut(BaseModel):
    id: uuid.UUID
    status: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AddOffersRequest(BaseModel):
    offers: list[dict[str, Any]]


def _run_out(run: DiscoveryRun) -> DiscoveryRunOut:
    return DiscoveryRunOut(id=run.id, status=run.status, request=run.request or {}, result=run.result, error=run.error, created_at=run.created_at, started_at=run.started_at, finished_at=run.finished_at)


async def _launch(payload: DiscoveryRequest, user: User, db: AsyncSession, settings: Settings) -> DiscoveryRun:
    allowed = [ats for ats in payload.ats if ats in SUPPORTED_ATS]
    if not allowed:
        raise HTTPException(status_code=400, detail="no supported ATS selected")
    active = await latest_run(db, user.id)
    active_age = None
    if active and active.created_at:
        created = active.created_at if active.created_at.tzinfo else active.created_at.replace(tzinfo=UTC)
        active_age = (datetime.now(UTC) - created).total_seconds()
    if active and active.status in ACTIVE_STATUSES and active_age is not None and active_age < RUN_TIMEOUT_SECONDS:
        return active
    run = await create_run(db, user.id, {"since_days": payload.since_days, "ats": allowed, "limit_per_ats": payload.limit_per_ats})
    start_run_task(run.id, settings)
    return run


@router.post("/runs", status_code=202)
async def create_discovery_run(payload: DiscoveryRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> DiscoveryRunOut:
    return _run_out(await _launch(payload, user, db, settings))


@router.get("/runs/latest")
async def get_latest_run(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> DiscoveryRunOut:
    run = await latest_run(db, user.id)
    if run is None:
        raise HTTPException(status_code=404, detail="no discovery runs")
    return _run_out(run)


@router.get("/runs/{run_id}")
async def get_discovery_run(run_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> DiscoveryRunOut:
    run = await get_run(db, user.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="discovery run not found")
    return _run_out(run)


@router.post("/reverse-ats", status_code=202, deprecated=True)
async def reverse_ats(payload: DiscoveryRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> DiscoveryRunOut:
    return _run_out(await _launch(payload, user, db, settings))


@router.post("/offers")
async def add_offers(payload: AddOffersRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    added = 0
    for value in payload.offers[:100]:
        try:
            offer = JobIngest(company=str(value["company"]), title=str(value["title"]), location=str(value.get("location") or ""), source=str(value.get("source") or value.get("ats") or "web-discovery"), posting_url=str(value["url"]), direct_application_url=str(value["url"]), posted_at=value.get("postedAt"), source_metadata=value)
        except (KeyError, ValueError):
            continue
        method = METHOD_REVERSE_ATS if is_reverse_scan_capable(offer.source) else METHOD_WEB_SEARCH if offer.source == "web-discovery" else METHOD_MANUAL
        job, _, _ = await ingest_discovery(db, offer, method=method, user_id=user.id)
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added from candidate discovery; awaiting cheap triage"))
        added += 1
    return {"added": added}


@router.get("/sources")
async def get_sources_overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await build_sources_overview(db, user.id)


@router.get("/morning-status")
async def get_morning_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Operational visibility for the shared morning cycle (Phase 5 follow-up
    §11) — reuses MorningRun rather than adding new status infrastructure.
    Global (not per-candidate), same as the reverse-ATS/watchlist work it
    reports on; every authenticated candidate can see the same run status."""
    run = await db.scalar(select(MorningRun).order_by(MorningRun.started_at.desc()).limit(1))
    if run is None:
        return {"status": "never_run", "started_at": None, "finished_at": None, "sources": {}}
    sources = (run.summary or {}).get("sources", {})
    return {"status": run.status, "started_at": run.started_at, "finished_at": run.finished_at, "sources": {name: outcome.get("status", "ok") for name, outcome in sources.items()}}


class AISearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


@router.post("/ai-search")
async def ai_search(payload: AISearchRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Hosted Explore AI Search (Phase 5 follow-up) — no CLI, no shared
    credential; runs server-side using THIS candidate's own encrypted
    Anthropic key (app.modules.ai_config)."""
    try:
        return await run_ai_search(db, settings, user, payload.query)
    except AISearchNotConfigured:
        raise HTTPException(status_code=409, detail="AI Search isn't configured for your account yet — add an Anthropic API key in Settings.")
    except AISearchRateLimited as error:
        raise HTTPException(status_code=429, detail=f"Please wait {error.retry_after_seconds:.0f}s before searching again.")


# ── Company Watchlist (Phase 5 §4) ──────────────────────────────────────────


@router.get("/watchlist", response_model=list[WatchedCompanyResponse])
async def get_watchlist(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await list_watched_companies(db, user.id)


@router.post("/watchlist", response_model=WatchedCompanyResponse, status_code=201)
async def add_watched_company(payload: WatchedCompanyCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        return await create_watched_company(db, user.id, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.patch("/watchlist/{company_id}", response_model=WatchedCompanyResponse)
async def edit_watched_company(company_id: uuid.UUID, payload: WatchedCompanyUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company = await get_watched_company(db, user.id, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="watched company not found")
    return await update_watched_company(db, company, payload)


@router.delete("/watchlist/{company_id}", status_code=204)
async def remove_watched_company(company_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company = await get_watched_company(db, user.id, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="watched company not found")
    await delete_watched_company(db, company)
