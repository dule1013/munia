import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    created_at: datetime
    updated_at: datetime


class ProfileResponse(BaseModel):
    user: UserResponse
    profile: dict[str, Any]
    master_cv: str
    onboarding_complete: bool
    updated_at: datetime


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    master_cv: str = Field(min_length=1, max_length=200_000)
    target_roles: list[str] = Field(min_length=1, max_length=10)
    current_location: str = Field(min_length=1, max_length=255)
    work_authorization: list[str] = Field(min_length=1, max_length=20)
    sponsorship_required: bool = False
    remote_preference: str = Field(max_length=100)
    relocation_preference: str = Field(max_length=255)
    compensation: dict[str, Any] = Field(default_factory=dict)


class ProfileUpdate(BaseModel):
    profile: dict[str, Any]


class MasterCvUpdate(BaseModel):
    content: str = Field(max_length=200_000)
