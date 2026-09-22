import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WatchedCompanyCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    careers_url: str | None = Field(default=None, max_length=2048)
    priority: int = Field(default=0, ge=0, le=10)
    enabled: bool = True


class WatchedCompanyUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    careers_url: str | None = Field(default=None, max_length=2048)
    priority: int | None = Field(default=None, ge=0, le=10)
    enabled: bool | None = None


class WatchedCompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    careers_url: str | None
    provider: str | None
    provider_tenant_id: str | None
    priority: int
    enabled: bool
    last_scanned_at: datetime | None
    scan_status: str | None
    last_scan_error: str | None
    created_at: datetime
    updated_at: datetime
