import uuid

from app.core.crypto import generate_key
from app.modules.ai_config import service as ai_config_service
from app.modules.candidates.models import User


async def seed_user(sessions, clerk_user_id: str) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


async def test_status_reports_not_configured_by_default(api):
    client, sessions, _ = api
    await seed_user(sessions, "clerk-a")
    resp = await client.get("/api/v1/ai-config/status", headers=headers("clerk-a"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert any(m["id"] == "claude-haiku-4-5-20251001" for m in body["available_models"])


async def test_set_and_status_reflects_configured_state_without_leaking_the_key(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")

    resp = await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-super-secret-value"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert "sk-ant-super-secret-value" not in resp.text
    assert "api_key" not in body

    status = await client.get("/api/v1/ai-config/status", headers=headers("clerk-a"))
    assert status.json()["configured"] is True


async def test_unsupported_model_is_rejected(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    resp = await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"provider": "anthropic", "model": "gpt-4o", "api_key": "sk-ant-x"})
    assert resp.status_code == 400


async def test_unsupported_provider_is_rejected(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    resp = await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"provider": "openai", "model": "claude-haiku-4-5-20251001", "api_key": "sk-x"})
    assert resp.status_code == 400


async def test_remove_clears_configuration(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-x"})
    resp = await client.delete("/api/v1/ai-config", headers=headers("clerk-a"))
    assert resp.status_code == 204
    status = await client.get("/api/v1/ai-config/status", headers=headers("clerk-a"))
    assert status.json()["configured"] is False


async def test_replace_overwrites_previous_key(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-old"})
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-sonnet-5", "api_key": "sk-ant-new"})

    async with sessions() as db:
        config = await ai_config_service.get_ai_config(db, user.id)
        assert config.model == "claude-sonnet-5"
        assert ai_config_service.decrypt_api_key(settings, config) == "sk-ant-new"


async def test_candidate_a_cannot_read_or_affect_candidate_b_config(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")

    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-a-secret"})

    status_b = await client.get("/api/v1/ai-config/status", headers=headers("clerk-b"))
    assert status_b.json()["configured"] is False

    await client.delete("/api/v1/ai-config", headers=headers("clerk-b"))
    status_a = await client.get("/api/v1/ai-config/status", headers=headers("clerk-a"))
    assert status_a.json()["configured"] is True


async def test_encrypted_key_is_bound_to_the_owning_user_via_aad(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user_a = await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-a-secret"})

    async with sessions() as db:
        config = await ai_config_service.get_ai_config(db, user_a.id)
        assert "sk-ant-a-secret" not in config.encrypted_api_key
        config.user_id = uuid.uuid4()  # simulate a copied ciphertext under a different AAD
        import pytest
        with pytest.raises(Exception):
            ai_config_service.decrypt_api_key(settings, config)
