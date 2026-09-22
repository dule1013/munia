import base64
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.crypto import generate_key
from app.modules.automation.batch import linkedin_alert_sync_all
from app.modules.candidates.models import User
from app.modules.discovery import gmail_client
from app.modules.discovery.linkedin_alerts import LINKEDIN_ALERT_SENDER
from app.modules.integrations import gmail_oauth, service
from app.modules.jobs.models import Job


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def gmail_message(msg_id: str, *, subject: str, body: str) -> dict:
    return {
        "id": msg_id,
        "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": f"LinkedIn Job Alerts <{LINKEDIN_ALERT_SENDER}>"},
                {"name": "Authentication-Results", "value": "mx.google.com; dmarc=pass"},
            ],
            "body": {"data": b64(body)},
        },
    }


async def seed_user(sessions, clerk_user_id: str) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def configure(settings):
    settings.google_oauth_client_id = "id"
    settings.google_oauth_client_secret = "secret"
    settings.google_oauth_redirect_uri = "https://api.example.com/cb"
    settings.integration_encryption_key = generate_key()


async def test_automation_isolates_one_candidates_failure_from_another(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    good_user = await seed_user(sessions, "clerk-good")
    bad_user = await seed_user(sessions, "clerk-bad")
    async with sessions() as db:
        await service.store_tokens(db, settings, user_id=good_user.id, provider="gmail", refresh_token="rt-good", account_email="good@gmail.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)
        await service.store_tokens(db, settings, user_id=bad_user.id, provider="gmail", refresh_token="rt-bad", account_email="bad@gmail.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)

    call_count = {"n": 0}

    async def fake_refresh(*, client_id, client_secret, refresh_token, http_client):
        call_count["n"] += 1
        if refresh_token == "rt-bad":
            raise gmail_oauth.OAuthError("token refresh failed (400) invalid_grant")
        return "access-token"

    good_alert = gmail_message("m1", subject="Acme Corp is hiring a Director of Engineering", body="https://www.linkedin.com/jobs/view/4001112222")

    async def fake_list(**kwargs):
        return [{"id": "m1"}]

    async def fake_get(*, access_token, http_client, message_id):
        return good_alert

    monkeypatch.setattr(gmail_oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(gmail_client, "list_messages", fake_list)
    monkeypatch.setattr(gmail_client, "get_message", fake_get)

    async with sessions() as db:
        result = await linkedin_alert_sync_all(db, settings)

    assert result["candidates"] == 2
    assert result["candidates_ok"] == 1
    assert result["candidates_failed"] == 1
    assert result["jobs_created"] == 1

    async with sessions() as db:
        bad_integration = await service.get_integration(db, bad_user.id, "gmail")
        good_integration = await service.get_integration(db, good_user.id, "gmail")
        assert bad_integration.status == "revoked"
        assert "invalid_grant" in bad_integration.last_error
        assert good_integration.status == "connected"
        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1


async def test_automation_skips_disconnected_integrations(api):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions, "clerk-a")
    async with sessions() as db:
        integration = await service.store_tokens(db, settings, user_id=user.id, provider="gmail", refresh_token="rt", account_email="a@b.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)
        await service.disconnect_integration(db, integration)

    async with sessions() as db:
        result = await linkedin_alert_sync_all(db, settings)
        assert result["candidates"] == 0
