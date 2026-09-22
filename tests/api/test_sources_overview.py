import uuid

from app.core.crypto import generate_key
from app.modules.candidates.models import CandidateProfile, User
from app.modules.integrations import gmail_oauth, service as integrations_service
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job


async def seed_user(sessions, clerk_user_id: str) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id))
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


def group_by_id(overview: dict, group_id: str) -> dict:
    return next(g for g in overview["groups"] if g["id"] == group_id)


async def test_sources_overview_groups_and_defaults(api):
    client, sessions, _ = api
    await seed_user(sessions, "clerk-a")
    resp = await client.get("/api/v1/discovery/sources", headers=headers("clerk-a"))
    assert resp.status_code == 200
    overview = resp.json()
    ids = [g["id"] for g in overview["groups"]]
    assert ids == ["linkedin", "network_scan", "company_watchlist", "job_feed", "web_discovery"]

    network = group_by_id(overview, "network_scan")
    assert {s["id"] for s in network["sources"]} == {"greenhouse", "lever", "ashby", "workday", "icims"}
    assert network["sources"][0]["metrics"] == {"discovered": 0, "eligible": 0, "worth_evaluating": 0, "applied": 0}

    linkedin = group_by_id(overview, "linkedin")["sources"][0]
    assert linkedin["status"] == "disconnected"

    watchlist = group_by_id(overview, "company_watchlist")
    assert watchlist["summary"]["companies_watched"] == 0

    feeds = group_by_id(overview, "job_feed")
    assert {s["id"] for s in feeds["sources"]} == {"wttj", "manfred"}
    assert feeds["sources"][0]["metrics_available"] is False


async def test_sources_overview_metrics_are_candidate_scoped(api):
    client, sessions, _ = api
    user_a = await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")

    async with sessions() as db:
        job, _, _ = await ingest_discovery(db, JobIngest(company="Acme", title="Director of Engineering", location="Remote", source="greenhouse", posting_url="https://job-boards.greenhouse.io/acme/1", direct_application_url="https://job-boards.greenhouse.io/acme/1"), method="reverse_ats")
        await db.commit()
        await add_candidate_job(db, user_a.id, CandidateJobCreate(job_id=job.id, eligibility="eligible", triage_result="worth"))

    resp_a = await client.get("/api/v1/discovery/sources", headers=headers("clerk-a"))
    greenhouse_a = next(s for s in group_by_id(resp_a.json(), "network_scan")["sources"] if s["id"] == "greenhouse")
    assert greenhouse_a["metrics"] == {"discovered": 1, "eligible": 1, "worth_evaluating": 1, "applied": 0}

    resp_b = await client.get("/api/v1/discovery/sources", headers=headers("clerk-b"))
    greenhouse_b = next(s for s in group_by_id(resp_b.json(), "network_scan")["sources"] if s["id"] == "greenhouse")
    assert greenhouse_b["metrics"] == {"discovered": 0, "eligible": 0, "worth_evaluating": 0, "applied": 0}


async def test_sources_overview_linkedin_reflects_connection_state(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions, "clerk-a")

    async with sessions() as db:
        await integrations_service.store_tokens(db, settings, user_id=user.id, provider="gmail", refresh_token="rt", account_email="a@b.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)

    resp = await client.get("/api/v1/discovery/sources", headers=headers("clerk-a"))
    linkedin = group_by_id(resp.json(), "linkedin")["sources"][0]
    assert linkedin["status"] == "connected"

    async with sessions() as db:
        integration = await integrations_service.get_integration(db, user.id, "gmail")
        await integrations_service.mark_sync_result(db, integration, ok=False, error="token refresh failed (400) invalid_grant")

    resp2 = await client.get("/api/v1/discovery/sources", headers=headers("clerk-a"))
    linkedin2 = group_by_id(resp2.json(), "linkedin")["sources"][0]
    assert linkedin2["status"] == "revoked"
    assert "invalid_grant" in linkedin2["last_error"]


async def test_sources_overview_watchlist_summary_reflects_scan_status(api):
    client, sessions, _ = api
    await seed_user(sessions, "clerk-a")

    created = await client.post("/api/v1/discovery/watchlist", headers=headers("clerk-a"), json={"company_name": "Docplanner", "careers_url": "https://jobs.ashbyhq.com/docplanner"})
    assert created.status_code == 201

    resp = await client.get("/api/v1/discovery/sources", headers=headers("clerk-a"))
    watchlist = group_by_id(resp.json(), "company_watchlist")
    assert watchlist["summary"]["companies_watched"] == 1
    assert watchlist["companies"][0]["provider"] == "ashby"
    assert watchlist["companies"][0]["scan_status"] == "never_scanned"
