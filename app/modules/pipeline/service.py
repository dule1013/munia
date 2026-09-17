import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.schemas import CandidateJobCreate, CandidateJobUpdate


async def candidate_job_for_user(db: AsyncSession, user_id: uuid.UUID, candidate_job_id: uuid.UUID) -> CandidateJob | None:
    return await db.scalar(select(CandidateJob).where(CandidateJob.id == candidate_job_id, CandidateJob.user_id == user_id))


async def add_candidate_job(db: AsyncSession, user_id: uuid.UUID, payload: CandidateJobCreate) -> CandidateJob:
    job = await db.get(Job, payload.job_id)
    if not job:
        raise ValueError("job not found")
    item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user_id, CandidateJob.job_id == payload.job_id))
    if item is None:
        item = CandidateJob(user_id=user_id, job_id=payload.job_id)
        db.add(item)
    item.eligibility = payload.eligibility
    item.triage_result = payload.triage_result
    item.triage_reason = payload.triage_reason
    await db.commit()
    await db.refresh(item)
    return item


async def update_candidate_job(db: AsyncSession, item: CandidateJob, payload: CandidateJobUpdate) -> CandidateJob:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item
