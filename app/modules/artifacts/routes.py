import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.artifacts.models import TailoredCv
from app.modules.artifacts.schemas import TailoredCvResponse, TailoredCvUpdate
from app.modules.artifacts.service import CvRenderError, CvValidationError, validate_and_render_cv
from app.modules.auth.dependencies import get_current_user
from app.modules.candidates.models import User
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob

router = APIRouter(prefix="/cvs", tags=["cvs"])


def cv_response(cv: TailoredCv, job: Job, candidate_job: CandidateJob, include_source: bool = False) -> TailoredCvResponse:
    return TailoredCvResponse(id=cv.id, job_id=cv.job_id, candidate_job_id=candidate_job.id, evaluation_id=cv.evaluation_id, company=job.company, title=job.title, source_html=cv.source_html if include_source else None, pdf_ready=bool(cv.artifact_key), manually_edited=cv.manually_edited, validation_status=cv.validation_status, generated_at=cv.generated_at, modified_at=cv.modified_at)


async def owned_cv(db: AsyncSession, user_id: uuid.UUID, cv_id: uuid.UUID) -> tuple[TailoredCv, Job, CandidateJob] | None:
    row = (await db.execute(select(TailoredCv, Job, CandidateJob).join(Job, Job.id == TailoredCv.job_id).join(CandidateJob, (CandidateJob.job_id == Job.id) & (CandidateJob.user_id == TailoredCv.user_id)).where(TailoredCv.id == cv_id, TailoredCv.user_id == user_id))).one_or_none()
    return row if row else None


@router.get("", response_model=list[TailoredCvResponse])
async def list_cvs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(TailoredCv, Job, CandidateJob).join(Job, Job.id == TailoredCv.job_id).join(CandidateJob, (CandidateJob.job_id == Job.id) & (CandidateJob.user_id == TailoredCv.user_id)).where(TailoredCv.user_id == user.id).order_by(TailoredCv.modified_at.desc()))).all()
    return [cv_response(cv, job, candidate_job) for cv, job, candidate_job in rows]


@router.get("/{cv_id}", response_model=TailoredCvResponse)
async def get_cv(cv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await owned_cv(db, user.id, cv_id)
    if not row:
        raise HTTPException(status_code=404, detail="tailored CV not found")
    return cv_response(*row, include_source=True)


@router.put("/{cv_id}", response_model=TailoredCvResponse)
async def update_cv(cv_id: uuid.UUID, payload: TailoredCvUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    row = await owned_cv(db, user.id, cv_id)
    if not row:
        raise HTTPException(status_code=404, detail="tailored CV not found")
    cv, job, candidate_job = row
    try:
        cv = await validate_and_render_cv(db, cv, payload.source_html, settings)
    except CvValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CvRenderError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return cv_response(cv, job, candidate_job, include_source=True)


@router.get("/{cv_id}/pdf")
async def get_cv_pdf(cv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    row = await owned_cv(db, user.id, cv_id)
    if not row or not row[0].artifact_key:
        raise HTTPException(status_code=404, detail="PDF not found")
    workspace = (settings.career_ops_workspace_root / str(user.id)).resolve()
    artifact = (workspace / row[0].artifact_key).resolve()
    if workspace not in artifact.parents or not artifact.is_file():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(artifact, media_type="application/pdf", filename=f"{row[1].company}-{row[1].title}.pdf")
