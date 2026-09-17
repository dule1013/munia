from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import AuthIdentity, get_current_user, get_identity
from app.modules.candidates.models import User
from app.modules.candidates.schemas import MasterCvUpdate, OnboardingRequest, ProfileResponse, ProfileUpdate, UserResponse
from app.modules.candidates.service import bootstrap_user, complete_onboarding, get_profile, update_structured_profile

router = APIRouter(prefix="/candidate", tags=["candidate"])


@router.post("/bootstrap", response_model=UserResponse)
async def bootstrap(identity: AuthIdentity = Depends(get_identity), db: AsyncSession = Depends(get_db)):
    return await bootstrap_user(db, identity.clerk_user_id, identity.email, identity.name)


@router.get("/profile", response_model=ProfileResponse)
async def profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    candidate = await get_profile(db, user.id)
    return ProfileResponse(user=user, profile=candidate.profile, master_cv=candidate.master_cv, onboarding_complete=candidate.onboarding_complete, updated_at=candidate.updated_at)


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(payload: ProfileUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    candidate = await get_profile(db, user.id)
    candidate = await update_structured_profile(db, candidate, payload.profile)
    return ProfileResponse(user=user, profile=candidate.profile, master_cv=candidate.master_cv, onboarding_complete=candidate.onboarding_complete, updated_at=candidate.updated_at)


@router.post("/onboarding", response_model=ProfileResponse)
async def onboarding(payload: OnboardingRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    candidate = await complete_onboarding(db, user, payload)
    return ProfileResponse(user=user, profile=candidate.profile, master_cv=candidate.master_cv, onboarding_complete=candidate.onboarding_complete, updated_at=candidate.updated_at)


@router.put("/master-cv", response_model=ProfileResponse)
async def update_master_cv(payload: MasterCvUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    candidate = await get_profile(db, user.id)
    candidate.master_cv = payload.content
    await db.commit()
    await db.refresh(candidate)
    return ProfileResponse(user=user, profile=candidate.profile, master_cv=candidate.master_cv, onboarding_complete=candidate.onboarding_complete, updated_at=candidate.updated_at)
