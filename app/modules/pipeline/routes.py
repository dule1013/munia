import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.artifacts.models import TailoredCv
from app.modules.auth.dependencies import get_current_user
from app.modules.candidates.models import User
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob, Evaluation
from app.modules.pipeline.schemas import CandidateJobCreate, CandidateJobResponse, CandidateJobUpdate, EvaluationResponse
from app.modules.pipeline.service import add_candidate_job, candidate_job_for_user, list_inbox, list_today, today_summary, update_candidate_job

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def response(item: CandidateJob, job: Job) -> CandidateJobResponse:
    return CandidateJobResponse.model_validate({**item.__dict__, "fit_score": float(item.fit_score) if item.fit_score is not None else None, "job": job})


@router.get("", response_model=list[CandidateJobResponse])
async def list_pipeline(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CandidateJob, Job).join(Job).where(CandidateJob.user_id == user.id).order_by(CandidateJob.updated_at.desc()))).all()
    return [response(item, job) for item, job in rows]


@router.post("", response_model=CandidateJobResponse)
async def create_candidate_job(payload: CandidateJobCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        item = await add_candidate_job(db, user.id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return response(item, await db.get_one(Job, item.job_id))


@router.get("/inbox", response_model=list[CandidateJobResponse])
async def get_inbox(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """All actionable jobs plausibly worth the candidate's attention —
    deliberately broader than /pipeline/today (Phase 5 follow-up)."""
    return [response(item, job) for item, job in await list_inbox(db, user.id)]


@router.get("/today", response_model=list[CandidateJobResponse])
async def get_today(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Only AI-qualified strong actionable opportunities, cumulative across
    runs, newest-qualifying first."""
    return [response(item, job) for item, job in await list_today(db, user.id)]


@router.get("/today/summary")
async def get_today_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await today_summary(db, user.id)


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(evaluation_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    evaluation = await db.scalar(select(Evaluation).join(CandidateJob).where(Evaluation.id == evaluation_id, CandidateJob.user_id == user.id))
    if not evaluation:
        raise HTTPException(status_code=404, detail="evaluation not found")
    return EvaluationResponse.model_validate({**evaluation.__dict__, "score": float(evaluation.score) if evaluation.score is not None else None})


@router.get("/{candidate_job_id}")
async def get_candidate_job(candidate_job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await candidate_job_for_user(db, user.id, candidate_job_id)
    if not item:
        raise HTTPException(status_code=404, detail="candidate job not found")
    job = await db.get_one(Job, item.job_id)
    evaluation = await db.scalar(select(Evaluation).where(Evaluation.candidate_job_id == item.id).order_by(Evaluation.evaluated_at.desc()).limit(1))
    cv = await db.scalar(select(TailoredCv).where(TailoredCv.user_id == user.id, TailoredCv.job_id == item.job_id))
    return {
        "candidate_job": response(item, job).model_dump(mode="json"),
        "evaluation": EvaluationResponse.model_validate({**evaluation.__dict__, "score": float(evaluation.score) if evaluation.score is not None else None}).model_dump(mode="json") if evaluation else None,
        "tailored_cv": {"id": str(cv.id), "pdf_ready": bool(cv.artifact_key), "manually_edited": cv.manually_edited} if cv else None,
    }


@router.patch("/{candidate_job_id}", response_model=CandidateJobResponse)
async def patch_candidate_job(candidate_job_id: uuid.UUID, payload: CandidateJobUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await candidate_job_for_user(db, user.id, candidate_job_id)
    if not item:
        raise HTTPException(status_code=404, detail="candidate job not found")
    item = await update_candidate_job(db, item, payload)
    return response(item, await db.get_one(Job, item.job_id))
