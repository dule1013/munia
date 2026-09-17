import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class JobIngest(BaseModel):
    company: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    location: str = Field(default="", max_length=500)
    description: str | None = None
    source: str = Field(default="unknown", max_length=100)
    external_source_id: str | None = Field(default=None, max_length=255)
    posting_url: HttpUrl
    direct_application_url: HttpUrl | None = None
    posted_at: datetime | None = None
    is_active: bool = True
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company: str
    title: str
    location: str
    description: str | None
    source: str
    posting_url: str
    direct_application_url: str | None
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool
