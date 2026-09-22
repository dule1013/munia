import base64
import uuid

from app.core.crypto import generate_key
from app.core.crypto import encrypt_secret
from app.modules.candidates.models import User
from app.modules.integrations import gmail_oauth, service
from app.modules.integrations.models import CandidateIntegration


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


def configure_oauth(settings) -> None:
    settings.google_oauth_client_id = "client-id.apps.googleusercontent.com"
    settings.google_oauth_client_secret = "test-client-secret"
    settings.google_oauth_redirect_uri = "https://api.example.com/api/v1/integrations/gmail/callback"
    settings.integration_encryption_key = generate_key()
    settings.web_app_url = "https://app.example.com"


async def test_status_defaults_to_disconnected(api):
    client, sessions, _ = api
    await seed_user(sessions)
    resp = await client.get("/api/v1/integrations/gmail/status", headers=headers("clerk-a"))
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"connected": False, "provider": "gmail", "status": "disconnected", "account_email": None, "scopes": None, "last_sync_at": None, "last_sync_status": None, "last_error": None}


async def test_connect_requires_oauth_configuration(api):
    client, sessions, _ = api
    await seed_user(sessions)
    resp = await client.post("/api/v1/integrations/gmail/connect", headers=headers("clerk-a"))
    assert resp.status_code == 503


async def test_connect_issues_authorization_url_with_minimal_scope_and_state(api):
    client, sessions, settings = api
    await seed_user(sessions)
    configure_oauth(settings)

    resp = await client.post("/api/v1/integrations/gmail/connect", headers=headers("clerk-a"))
    assert resp.status_code == 200
    body = resp.json()
    assert "state=" + body["state"] in body["authorization_url"]
    assert "gmail.readonly" in body["authorization_url"]
    # Only the readonly scope — no send/modify/contacts/calendar/drive.
    assert "gmail.send" not in body["authorization_url"]
    assert "gmail.modify" not in body["authorization_url"]
    assert "contacts" not in body["authorization_url"]
    assert "calendar" not in body["authorization_url"]
    assert "drive" not in body["authorization_url"]


async def test_callback_rejects_unknown_state(api):
    client, sessions, settings = api
    await seed_user(sessions)
    configure_oauth(settings)

    resp = await client.get("/api/v1/integrations/gmail/callback", params={"code": "abc", "state": "not-a-real-state"}, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "invalid_or_expired_state" in resp.headers["location"]


async def test_callback_happy_path_stores_encrypted_token_never_plaintext(api, monkeypatch):
    client, sessions, settings = api
    user = await seed_user(sessions)
    configure_oauth(settings)

    connect = await client.post("/api/v1/integrations/gmail/connect", headers=headers("clerk-a"))
    state = connect.json()["state"]

    async def fake_exchange(*, client_id, client_secret, redirect_uri, code, http_client):
        assert code == "auth-code-123"
        return {"access_token": "at-1", "refresh_token": "super-secret-refresh-token", "scope": gmail_oauth.GMAIL_READONLY_SCOPE}

    async def fake_email(*, access_token, http_client):
        return "candidate@gmail.com"

    monkeypatch.setattr(gmail_oauth, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(gmail_oauth, "fetch_account_email", fake_email)

    resp = await client.get("/api/v1/integrations/gmail/callback", params={"code": "auth-code-123", "state": state}, follow_redirects=False)
    assert resp.status_code in (302, 307)
    # Regression: this used to redirect to /settings/integrations, a page
    # that doesn't exist in the web app and 404'd in production. The
    # LinkedIn/Gmail panel lives on /discovery.
    assert resp.headers["location"].startswith(f"{settings.web_app_url}/discovery")
    assert "gmail=connected" in resp.headers["location"]

    status = await client.get("/api/v1/integrations/gmail/status", headers=headers("clerk-a"))
    body = status.json()
    assert body["connected"] is True
    assert body["account_email"] == "candidate@gmail.com"

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        assert integration is not None
        assert integration.encrypted_credentials is not None
        assert "super-secret-refresh-token" not in integration.encrypted_credentials
        assert base64.b64decode(integration.encrypted_credentials)  # valid base64 blob
        decrypted = service.decrypt_refresh_token(settings, integration)
        assert decrypted == "super-secret-refresh-token"


async def test_callback_state_is_single_use(api, monkeypatch):
    client, sessions, settings = api
    await seed_user(sessions)
    configure_oauth(settings)
    connect = await client.post("/api/v1/integrations/gmail/connect", headers=headers("clerk-a"))
    state = connect.json()["state"]

    async def fake_exchange(**kwargs):
        return {"access_token": "at", "refresh_token": "rt", "scope": gmail_oauth.GMAIL_READONLY_SCOPE}

    async def fake_email(**kwargs):
        return "candidate@gmail.com"

    monkeypatch.setattr(gmail_oauth, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(gmail_oauth, "fetch_account_email", fake_email)

    first = await client.get("/api/v1/integrations/gmail/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    assert "gmail=connected" in first.headers["location"]
    second = await client.get("/api/v1/integrations/gmail/callback", params={"code": "c2", "state": state}, follow_redirects=False)
    assert "invalid_or_expired_state" in second.headers["location"]


async def test_disconnect_clears_credentials(api):
    client, sessions, settings = api
    user = await seed_user(sessions)
    configure_oauth(settings)
    async with sessions() as db:
        await service.store_tokens(db, settings, user_id=user.id, provider="gmail", refresh_token="rt", account_email="a@b.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)

    resp = await client.post("/api/v1/integrations/gmail/disconnect", headers=headers("clerk-a"))
    assert resp.status_code == 204

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        assert integration.status == "disconnected"
        assert integration.encrypted_credentials is None


async def test_candidate_cannot_see_another_candidates_integration(api):
    client, sessions, settings = api
    user_a = await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")
    configure_oauth(settings)
    async with sessions() as db:
        await service.store_tokens(db, settings, user_id=user_a.id, provider="gmail", refresh_token="rt", account_email="a@b.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)

    status_b = await client.get("/api/v1/integrations/gmail/status", headers=headers("clerk-b"))
    assert status_b.json()["connected"] is False

    sync_b = await client.post("/api/v1/integrations/gmail/sync", headers=headers("clerk-b"))
    assert sync_b.status_code == 409

    disconnect_b = await client.post("/api/v1/integrations/gmail/disconnect", headers=headers("clerk-b"))
    assert disconnect_b.status_code == 204  # no-op for a user with no integration

    status_a_after = await client.get("/api/v1/integrations/gmail/status", headers=headers("clerk-a"))
    assert status_a_after.json()["connected"] is True  # untouched by clerk-b's disconnect


def test_encrypted_secret_round_trips_and_is_bound_to_context():
    key = generate_key()
    blob = encrypt_secret(key, "plaintext-refresh-token", aad="user-1:gmail")
    assert "plaintext-refresh-token" not in blob
    from app.core.crypto import decrypt_secret

    assert decrypt_secret(key, blob, aad="user-1:gmail") == "plaintext-refresh-token"


def test_encrypted_secret_rejects_mismatched_aad():
    from cryptography.exceptions import InvalidTag

    from app.core.crypto import decrypt_secret

    key = generate_key()
    blob = encrypt_secret(key, "plaintext-refresh-token", aad="user-1:gmail")
    try:
        decrypt_secret(key, blob, aad="user-2:gmail")
        assert False, "decrypting with the wrong AAD must fail"
    except InvalidTag:
        pass


async def test_revoked_refresh_token_surfaces_as_distinct_status(api, monkeypatch):
    from app.modules.discovery.linkedin_ingest import sync_gmail_linkedin_alerts

    client, sessions, settings = api
    user = await seed_user(sessions)
    configure_oauth(settings)
    async with sessions() as db:
        integration = await service.store_tokens(db, settings, user_id=user.id, provider="gmail", refresh_token="revoked-rt", account_email="a@b.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)

    async def fake_refresh(**kwargs):
        raise gmail_oauth.OAuthError("token refresh failed (400) invalid_grant")

    monkeypatch.setattr(gmail_oauth, "refresh_access_token", fake_refresh)

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        result = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert result["status"] == "error"

    status = await client.get("/api/v1/integrations/gmail/status", headers=headers("clerk-a"))
    body = status.json()
    assert body["status"] == "revoked"
    assert "invalid_grant" in body["last_error"]
