import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.candidates.models import User
from app.modules.jobs.models import Job
from app.modules.jobs.schemas import JobResponse
from app.modules.pipeline.models import CandidateJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
async def list_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Job).join(CandidateJob).where(CandidateJob.user_id == user.id).order_by(Job.posted_at.desc().nullslast(), Job.first_seen_at.desc()))
    return list(rows.unique())


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.scalar(select(Job).join(CandidateJob).where(Job.id == job_id, CandidateJob.user_id == user.id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
