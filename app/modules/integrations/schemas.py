import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IntegrationStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    connected: bool
    provider: str
    status: str
    account_email: str | None = None
    scopes: str | None = None
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    last_error: str | None = None


class ConnectResponse(BaseModel):
    authorization_url: str
    state: str


class SyncResultResponse(BaseModel):
    status: str
    messages_scanned: int = 0
    messages_skipped_untrusted: int = 0
    messages_skipped_malformed: int = 0
    jobs_found: int = 0
    jobs_created: int = 0
    jobs_attached: int = 0
    error: str | None = None


class IntegrationId(BaseModel):
    id: uuid.UUID
