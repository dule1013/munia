from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import AuthIdentity, get_identity

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/session")
async def session(identity: AuthIdentity = Depends(get_identity)) -> dict[str, str]:
    return {"clerk_user_id": identity.clerk_user_id}
