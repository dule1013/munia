from datetime import datetime

from pydantic import BaseModel, Field


class AIModelOption(BaseModel):
    id: str
    label: str
    cost_note: str


class AIConfigStatus(BaseModel):
    configured: bool
    provider: str | None = None
    model: str | None = None
    updated_at: datetime | None = None
    available_models: list[AIModelOption] = Field(default_factory=list)


class AIConfigSet(BaseModel):
    provider: str = "anthropic"
    model: str
    api_key: str = Field(min_length=1, max_length=500)


class AISearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
