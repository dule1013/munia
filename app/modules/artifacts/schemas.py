import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TailoredCvResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    candidate_job_id: uuid.UUID
    evaluation_id: uuid.UUID | None
    company: str
    title: str
    source_html: str | None = None
    pdf_ready: bool
    manually_edited: bool
    validation_status: str
    generated_at: datetime
    modified_at: datetime


class TailoredCvUpdate(BaseModel):
    source_html: str = Field(max_length=500_000)
