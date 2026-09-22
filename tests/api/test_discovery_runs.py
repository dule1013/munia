import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.automation.runner import CommandResult
from app.modules.candidates.models import User
from app.modules.discovery import service
from app.modules.discovery.service import execute_run


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:  # type: AsyncSession
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


def patch_scan(monkeypatch, tmp_path, workspace, result=None, raises=None):
    async def fake_prepare(db, user_id, settings):
        return workspace

    async def fake_run(ws, settings, script, *arguments, timeout=900):
        if raises is not None:
            raise raises
        return result

    monkeypatch.setattr(service, "prepare_workspace", fake_prepare)
    monkeypatch.setattr(service, "run_in_workspace", fake_run)


SUCCESS_PAYLOAD = json.dumps({
    "offers": [{"url": "https://x/1", "company": "A", "title": "Eng", "location": "Remote", "ats": "greenhouse", "postedAt": "2026-09-20"}],
    "companiesScanned": 3,
    "unreachableBoards": 1,
    "capHit": False,
    "datasetStatus": {"greenhouse": "ok"},
    "postingsDroppedNoDate": 0,
})


async def test_run_lifecycle_does_not_hold_session_during_scan(api, monkeypatch, tmp_path):
    client, sessions, settings = api
    await seed_user(sessions)
    patch_scan(monkeypatch, tmp_path, tmp_path, result=CommandResult(0, SUCCESS_PAYLOAD, ""))

    response = await client.post("/api/v1/discovery/runs", headers=headers("clerk-a"), json={"since_days": 7, "ats": ["greenhouse"], "limit_per_ats": 10})
    assert response.status_code == 202
    run_id = response.json()["id"]
    assert response.json()["status"] in {"queued", "running"}

    await execute_run(uuid.UUID(run_id), settings, session_factory=sessions)

    run = (await client.get(f"/api/v1/discovery/runs/{run_id}", headers=headers("clerk-a"))).json()
    assert run["status"] == "succeeded"
    assert len(run["result"]["offers"]) == 1
    assert run["result"]["companiesScanned"] == 3
    assert run["finished_at"] is not None


async def test_failed_scan_marks_run_failed(api, monkeypatch, tmp_path):
    client, sessions, settings = api
    await seed_user(sessions)
    patch_scan(monkeypatch, tmp_path, tmp_path, result=CommandResult(1, "", "boom"))

    response = await client.post("/api/v1/discovery/runs", headers=headers("clerk-a"), json={})
    run_id = response.json()["id"]
    await execute_run(uuid.UUID(run_id), settings, session_factory=sessions)

    run = (await client.get(f"/api/v1/discovery/runs/{run_id}", headers=headers("clerk-a"))).json()
    assert run["status"] == "failed"
    assert "boom" in run["error"]
    assert run["finished_at"] is not None


async def test_timeout_marks_run_failed(api, monkeypatch, tmp_path):
    client, sessions, settings = api
    await seed_user(sessions)
    patch_scan(monkeypatch, tmp_path, tmp_path, raises=TimeoutError())

    response = await client.post("/api/v1/discovery/runs", headers=headers("clerk-a"), json={})
    run_id = response.json()["id"]
    await execute_run(uuid.UUID(run_id), settings, session_factory=sessions)

    run = (await client.get(f"/api/v1/discovery/runs/{run_id}", headers=headers("clerk-a"))).json()
    assert run["status"] == "failed"
    assert run["error"] == "discovery timed out"


async def test_runs_are_user_scoped(api, monkeypatch, tmp_path):
    client, sessions, _ = api
    await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")
    patch_scan(monkeypatch, tmp_path, tmp_path, result=CommandResult(0, SUCCESS_PAYLOAD, ""))

    response = await client.post("/api/v1/discovery/runs", headers=headers("clerk-a"), json={})
    run_id = response.json()["id"]

    assert (await client.get(f"/api/v1/discovery/runs/{run_id}", headers=headers("clerk-b"))).status_code == 404
    assert (await client.get("/api/v1/discovery/runs/latest", headers=headers("clerk-b"))).status_code == 404
    assert (await client.get(f"/api/v1/discovery/runs/{run_id}", headers=headers("clerk-a"))).status_code == 200


async def test_active_run_is_reused(api, monkeypatch, tmp_path):
    client, sessions, settings = api
    await seed_user(sessions)
    gate = asyncio.Event()

    async def fake_prepare(db, user_id, settings_):
        return tmp_path

    async def fake_run(ws, settings_, script, *arguments, timeout=900):
        await gate.wait()
        return CommandResult(0, SUCCESS_PAYLOAD, "")

    monkeypatch.setattr(service, "prepare_workspace", fake_prepare)
    monkeypatch.setattr(service, "run_in_workspace", fake_run)

    first = await client.post("/api/v1/discovery/runs", headers=headers("clerk-a"), json={})
    second = await client.post("/api/v1/discovery/runs", headers=headers("clerk-a"), json={})
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    gate.set()


async def test_orphaned_runs_fail_on_restart(api, monkeypatch, tmp_path):
    client, sessions, settings = api
    await seed_user(sessions)
    patch_scan(monkeypatch, tmp_path, tmp_path, result=CommandResult(0, SUCCESS_PAYLOAD, ""))
    run_id = (await client.post("/api/v1/discovery/runs", headers=headers("clerk-a"), json={"since_days": 7, "ats": ["greenhouse"], "limit_per_ats": 10})).json()["id"]
    assert await service.fail_orphaned_runs(session_factory=sessions) == 1
    run = (await client.get(f"/api/v1/discovery/runs/{run_id}", headers=headers("clerk-a"))).json()
    assert run["status"] == "failed"
    assert "restart" in run["error"]
    assert run["finished_at"] is not None
