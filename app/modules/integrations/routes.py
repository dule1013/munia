import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.candidates.models import User
from app.modules.discovery.linkedin_ingest import sync_gmail_linkedin_alerts
from app.modules.integrations import gmail_oauth, service
from app.modules.integrations.schemas import ConnectResponse, IntegrationStatusResponse, SyncResultResponse

router = APIRouter(prefix="/integrations", tags=["integrations"])

PROVIDER = "gmail"


def _require_oauth_configured(settings: Settings) -> None:
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret and settings.google_oauth_redirect_uri and settings.integration_encryption_key):
        raise HTTPException(status_code=503, detail="Gmail integration is not configured on this deployment")


@router.get("/gmail/status", response_model=IntegrationStatusResponse)
async def gmail_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> IntegrationStatusResponse:
    integration = await service.get_integration(db, user.id, PROVIDER)
    if integration is None:
        return IntegrationStatusResponse(connected=False, provider=PROVIDER, status="disconnected")
    return IntegrationStatusResponse(
        connected=integration.status == "connected",
        provider=PROVIDER,
        status=integration.status,
        account_email=integration.account_email,
        scopes=integration.scopes,
        last_sync_at=integration.last_sync_at,
        last_sync_status=integration.last_sync_status,
        last_error=integration.last_error,
    )


@router.post("/gmail/connect", response_model=ConnectResponse)
async def gmail_connect(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> ConnectResponse:
    _require_oauth_configured(settings)
    state = await service.create_oauth_state(db, user.id, PROVIDER)
    url = gmail_oauth.build_authorization_url(client_id=settings.google_oauth_client_id, redirect_uri=settings.google_oauth_redirect_uri, state=state.state)
    return ConnectResponse(authorization_url=url, state=state.state)


@router.get("/gmail/callback")
async def gmail_callback(code: str | None = None, state: str | None = None, error: str | None = None, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    _require_oauth_configured(settings)
    target = f"{settings.web_app_url.rstrip('/')}/settings/integrations"
    if error:
        return RedirectResponse(url=f"{target}?gmail=error&reason={error}")
    if not code or not state:
        return RedirectResponse(url=f"{target}?gmail=error&reason=missing_code_or_state")

    oauth_state = await service.consume_oauth_state(db, state, PROVIDER)
    if oauth_state is None:
        return RedirectResponse(url=f"{target}?gmail=error&reason=invalid_or_expired_state")

    try:
        async with httpx.AsyncClient(timeout=15) as http_client:
            tokens = await gmail_oauth.exchange_code_for_tokens(client_id=settings.google_oauth_client_id, client_secret=settings.google_oauth_client_secret, redirect_uri=settings.google_oauth_redirect_uri, code=code, http_client=http_client)
            account_email = await gmail_oauth.fetch_account_email(access_token=tokens["access_token"], http_client=http_client)
    except gmail_oauth.OAuthError:
        return RedirectResponse(url=f"{target}?gmail=error&reason=token_exchange_failed")

    await service.store_tokens(db, settings, user_id=oauth_state.user_id, provider=PROVIDER, refresh_token=tokens["refresh_token"], account_email=account_email, scopes=tokens.get("scope", gmail_oauth.GMAIL_READONLY_SCOPE))
    return RedirectResponse(url=f"{target}?gmail=connected")


@router.post("/gmail/disconnect", status_code=204)
async def gmail_disconnect(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    integration = await service.get_integration(db, user.id, PROVIDER)
    if integration is None:
        return
    await service.disconnect_integration(db, integration)


@router.post("/gmail/sync", response_model=SyncResultResponse)
async def gmail_sync_now(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> SyncResultResponse:
    integration = await service.get_integration(db, user.id, PROVIDER)
    if integration is None or integration.status not in {"connected", "error", "revoked"} or not integration.encrypted_credentials:
        raise HTTPException(status_code=409, detail="Gmail is not connected for this candidate")
    result = await sync_gmail_linkedin_alerts(db, integration, settings)
    return SyncResultResponse(**result)
