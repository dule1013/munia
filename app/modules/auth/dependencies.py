import asyncio
from dataclasses import dataclass

import httpx
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.candidates.models import User


@dataclass(frozen=True)
class AuthIdentity:
    clerk_user_id: str
    email: str
    name: str


def _test_identity(request: Request, settings: Settings) -> AuthIdentity | None:
    if settings.environment != "test" or not settings.auth_test_mode:
        return None
    user_id = request.headers.get("x-test-clerk-user-id", "").strip()
    if not user_id:
        return None
    email = request.headers.get("x-test-clerk-email", "").strip() or f"{user_id}@test.invalid"
    name = request.headers.get("x-test-clerk-name", "").strip() or user_id
    return AuthIdentity(user_id, email, name)


def clerk_identity(user: object) -> AuthIdentity:
    primary_id = getattr(user, "primary_email_address_id", None)
    primary = next((item for item in getattr(user, "email_addresses", []) if getattr(item, "id", None) == primary_id), None)
    verification = getattr(primary, "verification", None)
    if primary is None or getattr(verification, "status", None) != "verified":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="a verified primary Clerk email is required")
    first = str(getattr(user, "first_name", None) or "").strip()
    last = str(getattr(user, "last_name", None) or "").strip()
    email = str(getattr(primary, "email_address"))
    return AuthIdentity(str(getattr(user, "id")), email, " ".join(part for part in (first, last) if part) or email.split("@", 1)[0])


async def get_identity(request: Request, settings: Settings = Depends(get_settings)) -> AuthIdentity:
    test_identity = _test_identity(request, settings)
    if test_identity:
        return test_identity
    if settings.environment == "test" and settings.auth_test_mode:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    if not settings.clerk_secret_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="authentication is not configured")
    sdk = Clerk(bearer_auth=settings.clerk_secret_key)
    clerk_request = httpx.Request(request.method, str(request.url), headers=dict(request.headers))
    options = AuthenticateRequestOptions(
        secret_key=settings.clerk_secret_key,
        jwt_key=settings.clerk_jwt_key or None,
        authorized_parties=settings.clerk_authorized_parties,
        accepts_token=["session_token"],
    )
    state = await asyncio.to_thread(sdk.authenticate_request, clerk_request, options)
    if not state.is_signed_in or not state.payload or not state.payload.get("sub"):
        print("Clerk verification rejected request:", {"status": str(state.status), "reason": str(state.reason), "message": str(getattr(state, "message", ""))}, flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    clerk_user_id = str(state.payload["sub"])
    try:
        clerk_user = await asyncio.to_thread(sdk.users.get, user_id=clerk_user_id)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="could not resolve Clerk identity") from error
    identity = clerk_identity(clerk_user)
    if identity.clerk_user_id != clerk_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clerk identity mismatch")
    return identity


async def get_current_user(identity: AuthIdentity = Depends(get_identity), db: AsyncSession = Depends(get_db)) -> User:
    user = await db.scalar(select(User).where(User.clerk_user_id == identity.clerk_user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="candidate account is not provisioned")
    return user
