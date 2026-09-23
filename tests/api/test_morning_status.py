import uuid

from app.modules.candidates.models import User
from app.modules.discovery.models import MorningRun


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


async def test_morning_status_never_run(api):
    client, sessions, _ = api
    await seed_user(sessions)
    resp = await client.get("/api/v1/discovery/morning-status", headers=headers("clerk-a"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "never_run"


async def test_morning_status_reports_latest_run(api):
    client, sessions, _ = api
    await seed_user(sessions)
    async with sessions() as db:
        run = MorningRun(id=uuid.uuid4(), status="completed_with_warnings", summary={"sources": {"linkedin": {"candidates": 1}, "workday": {"status": "error", "error": "timeout"}}})
        db.add(run)
        await db.commit()

    resp = await client.get("/api/v1/discovery/morning-status", headers=headers("clerk-a"))
    body = resp.json()
    assert body["status"] == "completed_with_warnings"
    assert body["sources"]["workday"] == "error"
    assert body["sources"]["linkedin"] == "ok"
