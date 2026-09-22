import uuid

from app.modules.candidates.models import User
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


async def test_provenance_lists_every_channel_without_duplicating_the_job(api):
    client, sessions, _ = api
    user = await seed_user(sessions)

    async with sessions() as db:
        linkedin_job, _, _ = await ingest_discovery(db, JobIngest(company="Acme", title="Director of Engineering", location="", source="linkedin", posting_url="https://www.linkedin.com/jobs/view/1112223334", direct_application_url="https://www.linkedin.com/jobs/view/1112223334"), method="email_alert")
        await db.commit()
        job, _, created = await ingest_discovery(db, JobIngest(company="Acme", title="Director of Engineering", location="", source="greenhouse", posting_url="https://job-boards.greenhouse.io/acme/1", direct_application_url="https://job-boards.greenhouse.io/acme/1"), method="reverse_ats")
        await db.commit()
        assert created is False
        assert job.id == linkedin_job.id
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id))

    # Canonical URL/source is upgraded to the strong ATS source...
    detail = await client.get(f"/api/v1/jobs/{job.id}", headers=headers("clerk-a"))
    assert detail.status_code == 200
    body = detail.json()
    assert body["source"] == "greenhouse"
    assert body["posting_url"] == "https://job-boards.greenhouse.io/acme/1"

    # ...but LinkedIn stays visible as a discovery channel, and there is
    # still exactly ONE job, not two.
    discoveries = await client.get(f"/api/v1/jobs/{job.id}/discoveries", headers=headers("clerk-a"))
    assert discoveries.status_code == 200
    sources = {d["source"] for d in discoveries.json()}
    assert sources == {"linkedin", "greenhouse"}
    all_jobs = await client.get("/api/v1/jobs", headers=headers("clerk-a"))
    assert len(all_jobs.json()) == 1


async def test_provenance_excludes_candidate_identifying_metadata(api):
    client, sessions, _ = api
    user = await seed_user(sessions)
    async with sessions() as db:
        job, _, _ = await ingest_discovery(db, JobIngest(company="Acme", title="Director of Engineering", source="linkedin", posting_url="https://www.linkedin.com/jobs/view/999", direct_application_url="https://www.linkedin.com/jobs/view/999"), method="email_alert", user_id=user.id)
        await db.commit()
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id))

    resp = await client.get(f"/api/v1/jobs/{job.id}/discoveries", headers=headers("clerk-a"))
    body = resp.json()
    assert len(body) == 1
    assert set(body[0].keys()) == {"source", "method", "first_seen_at", "last_seen_at"}


async def test_provenance_is_scoped_to_jobs_in_the_candidates_own_pipeline(api):
    client, sessions, _ = api
    await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")
    async with sessions() as db:
        job, _, _ = await ingest_discovery(db, JobIngest(company="Acme", title="Director of Engineering", source="greenhouse", posting_url="https://job-boards.greenhouse.io/acme/9", direct_application_url="https://job-boards.greenhouse.io/acme/9"), method="reverse_ats")
        await db.commit()

    # Neither candidate has this job in their pipeline yet.
    resp = await client.get(f"/api/v1/jobs/{job.id}/discoveries", headers=headers("clerk-b"))
    assert resp.status_code == 404
