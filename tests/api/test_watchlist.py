import uuid

from app.modules.candidates.models import User
from app.modules.discovery.sources import detect_provider
from app.modules.discovery.watchlist_service import distinct_scan_targets


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


async def test_create_list_update_delete_watched_company(api):
    client, sessions, _ = api
    await seed_user(sessions)

    created = await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "Docplanner", "careers_url": "https://jobs.ashbyhq.com/docplanner", "priority": 5})
    assert created.status_code == 201
    body = created.json()
    assert body["company_name"] == "Docplanner"
    assert body["provider"] == "ashby"
    assert body["provider_tenant_id"] == "docplanner"
    assert body["scan_status"] == "never_scanned"
    company_id = body["id"]

    listed = await client.get("/api/v1/discovery/watchlist", headers=headers("clerk-a"))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = await client.patch(f"/api/v1/discovery/watchlist/{company_id}", headers=headers("clerk-a"), json={"priority": 9, "enabled": False})
    assert updated.status_code == 200
    assert updated.json()["priority"] == 9
    assert updated.json()["enabled"] is False

    deleted = await client.delete(f"/api/v1/discovery/watchlist/{company_id}", headers=headers("clerk-a"))
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/discovery/watchlist", headers=headers("clerk-a"))).json() == []


async def test_duplicate_company_on_watchlist_is_rejected(api):
    client, sessions, _ = api
    await seed_user(sessions)

    first = await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "Docplanner"})
    assert first.status_code == 201
    duplicate = await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "  docplanner  "})
    assert duplicate.status_code == 409


async def test_watchlist_is_candidate_isolated(api):
    client, sessions, _ = api
    await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")

    created = await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "Docplanner"})
    company_id = created.json()["id"]

    assert (await client.get("/api/v1/discovery/watchlist", headers=headers("clerk-b"))).json() == []
    assert (await client.patch(f"/api/v1/discovery/watchlist/{company_id}", headers=headers("clerk-b"), json={"priority": 3})).status_code == 404
    assert (await client.delete(f"/api/v1/discovery/watchlist/{company_id}", headers=headers("clerk-b"))).status_code == 404
    # Untouched from clerk-a's perspective.
    assert (await client.get("/api/v1/discovery/watchlist", headers=headers("clerk-a"))).json()[0]["priority"] == 0


async def test_shared_company_watched_by_two_candidates_is_one_scan_target(api):
    client, sessions, _ = api
    await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")

    await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "Docplanner", "careers_url": "https://jobs.ashbyhq.com/docplanner"})
    await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-b"), json={"company_name": "Docplanner", "careers_url": "https://jobs.ashbyhq.com/docplanner"})
    await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "Snyk", "careers_url": "https://jobs.ashbyhq.com/snyk"})

    async with sessions() as db:
        targets = await distinct_scan_targets(db)

    by_key = {t.careers_url: t for t in targets}
    assert len(targets) == 2
    docplanner = by_key["https://jobs.ashbyhq.com/docplanner"]
    assert len(docplanner.watcher_user_ids) == 2
    assert len(docplanner.watchlist_entry_ids) == 2
    snyk = by_key["https://jobs.ashbyhq.com/snyk"]
    assert len(snyk.watcher_user_ids) == 1


async def test_distinct_scan_targets_excludes_disabled_by_default(api):
    client, sessions, _ = api
    await seed_user(sessions)
    created = await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "Docplanner"})
    await client.patch(f"/api/v1/discovery/watchlist/{created.json()['id']}", headers=headers("clerk-a"), json={"enabled": False})

    async with sessions() as db:
        targets = await distinct_scan_targets(db)
        all_targets = await distinct_scan_targets(db, enabled_only=False)

    assert targets == []
    assert len(all_targets) == 1


def test_detect_provider_from_known_ats_hosts():
    assert detect_provider("https://jobs.ashbyhq.com/docplanner") == ("ashby", "docplanner")
    assert detect_provider("https://job-boards.greenhouse.io/acme") == ("greenhouse", "acme")
    assert detect_provider("https://acme.recruitee.com") == ("recruitee", "acme")
    assert detect_provider("https://travelperk.pinpointhq.com") == ("pinpoint", "travelperk")
    assert detect_provider("https://careers-travelperk.icims.com/jobs/search") == ("icims", "travelperk")
    assert detect_provider("") == (None, None)
    assert detect_provider("https://example.com/careers") == (None, None)
