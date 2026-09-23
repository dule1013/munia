import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.jobs.schemas import JobResponse


class CandidateJobCreate(BaseModel):
    job_id: uuid.UUID
    eligibility: str | None = Field(default=None, max_length=100)
    triage_result: str | None = Field(default=None, pattern="^(worth|uncertain|discard)$")
    triage_reason: str | None = None


class CandidateJobUpdate(BaseModel):
    eligibility: str | None = Field(default=None, max_length=100)
    triage_result: str | None = Field(default=None, pattern="^(worth|uncertain|discard)$")
    triage_reason: str | None = None
    triage_metadata: dict = Field(default_factory=dict)
    fit_score: float | None = Field(default=None, ge=0, le=5)
    recommendation: str | None = Field(default=None, max_length=100)
    pipeline_status: str | None = Field(default=None, max_length=50)
    saved: bool | None = None
    skipped: bool | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_job_id: uuid.UUID
    report_number: int | None
    score: float | None
    recommendation: str | None
    report_markdown: str
    evaluated_at: datetime


class CandidateJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    eligibility: str | None
    triage_result: str | None
    triage_reason: str | None
    triage_metadata: dict
    fit_score: float | None
    recommendation: str | None
    pipeline_status: str
    saved: bool
    skipped: bool
    notes: str
    evaluated_at: datetime | None
    applied_at: datetime | None
    ai_fit: str | None
    ai_fit_reason: str | None
    ai_fit_confidence: str | None
    ai_fit_assessed_at: datetime | None
    job: JobResponse
