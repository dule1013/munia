import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.artifacts.models import TailoredCv
from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob, Evaluation


async def seed(sessions):
    async with sessions() as db:  # type: AsyncSession
        user_a = User(id=uuid.uuid4(), clerk_user_id="clerk-a", email="a@example.com", name="Candidate A")
        user_b = User(id=uuid.uuid4(), clerk_user_id="clerk-b", email="b@example.com", name="Candidate B")
        job = Job(id=uuid.uuid4(), canonical_key="shared-key", canonical_url="https://jobs.example.com/1", company="Shared Co", title="Engineering Director", location="Remote", source="test", posting_url="https://jobs.example.com/1", direct_application_url="https://jobs.example.com/1", source_metadata={})
        db.add_all([user_a, user_b, job])
        await db.flush()
        db.add_all([CandidateProfile(user_id=user_a.id, master_cv="# A", profile={"identity": "A"}, profile_yaml="identity: A", profile_markdown="# A", cv_facts={"facts": ["A"]}, onboarding_complete=True), CandidateProfile(user_id=user_b.id, master_cv="# B", profile={"identity": "B"}, profile_yaml="identity: B", profile_markdown="# B", cv_facts={"facts": ["B"]}, onboarding_complete=True)])
        candidate_a = CandidateJob(id=uuid.uuid4(), user_id=user_a.id, job_id=job.id, pipeline_status="Applied", eligibility="eligible", triage_result="worth", triage_reason="A fit")
        candidate_b = CandidateJob(id=uuid.uuid4(), user_id=user_b.id, job_id=job.id, pipeline_status="Skipped", eligibility="ineligible", triage_result="discard", triage_reason="B mismatch", skipped=True)
        db.add_all([candidate_a, candidate_b])
        await db.flush()
        evaluation_a = Evaluation(id=uuid.uuid4(), candidate_job_id=candidate_a.id, report_number=1, score=4.7, recommendation="Apply", report_markdown="Private A report")
        evaluation_b = Evaluation(id=uuid.uuid4(), candidate_job_id=candidate_b.id, report_number=1, score=1.2, recommendation="Discard", report_markdown="Private B report")
        db.add_all([evaluation_a, evaluation_b])
        await db.flush()
        cv_a = TailoredCv(id=uuid.uuid4(), user_id=user_a.id, job_id=job.id, evaluation_id=evaluation_a.id, source_html="<html>Private A CV</html>", manually_edited=True, validation_status="valid")
        cv_b = TailoredCv(id=uuid.uuid4(), user_id=user_b.id, job_id=job.id, evaluation_id=evaluation_b.id, source_html="<html>Private B CV</html>", validation_status="valid")
        db.add_all([cv_a, cv_b])
        await db.commit()
        return user_a, user_b, job, candidate_a, candidate_b, evaluation_a, evaluation_b, cv_a, cv_b


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


async def test_unauthenticated_requests_are_rejected(api):
    client, _, _ = api
    assert (await client.get("/api/v1/candidate/profile")).status_code == 401
    assert (await client.get("/api/v1/pipeline")).status_code == 401
    assert (await client.get("/api/v1/cvs")).status_code == 401


async def test_browser_supplied_email_cannot_claim_migrated_candidate(api):
    client, sessions, _ = api
    async with sessions() as db:
        victim = User(id=uuid.uuid4(), clerk_user_id="migration:victim", email="victim@example.com", name="Victim")
        db.add(victim)
        await db.flush()
        db.add(CandidateProfile(user_id=victim.id, master_cv="# Private victim CV", profile={}, profile_yaml="", profile_markdown="", cv_facts={}))
        await db.commit()

    response = await client.post(
        "/api/v1/candidate/bootstrap",
        headers={"x-test-clerk-user-id": "clerk-attacker", "x-test-clerk-email": "attacker@example.com", "x-test-clerk-name": "Attacker"},
        json={"email": "victim@example.com", "name": "Victim"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "attacker@example.com"
    async with sessions() as db:
        victim = await db.scalar(select(User).where(User.email == "victim@example.com"))
        attacker = await db.scalar(select(User).where(User.email == "attacker@example.com"))
        assert victim.clerk_user_id == "migration:victim"
        assert attacker.clerk_user_id == "clerk-attacker"
        assert attacker.id != victim.id


async def test_candidate_data_is_isolated_while_job_is_shared(api):
    client, sessions, settings = api
    seeded = await seed(sessions)
    _, _, job, candidate_a, candidate_b, evaluation_a, evaluation_b, cv_a, cv_b = seeded

    profile_a = (await client.get("/api/v1/candidate/profile", headers=headers("clerk-a"))).json()
    profile_b = (await client.get("/api/v1/candidate/profile", headers=headers("clerk-b"))).json()
    assert profile_a["master_cv"] == "# A"
    assert profile_b["master_cv"] == "# B"

    pipeline_a = (await client.get("/api/v1/pipeline", headers=headers("clerk-a"))).json()
    pipeline_b = (await client.get("/api/v1/pipeline", headers=headers("clerk-b"))).json()
    assert pipeline_a[0]["job_id"] == pipeline_b[0]["job_id"] == str(job.id)
    assert pipeline_a[0]["pipeline_status"] == "Applied"
    assert pipeline_b[0]["pipeline_status"] == "Skipped"
    assert pipeline_a[0]["triage_reason"] == "A fit"
    assert pipeline_b[0]["triage_reason"] == "B mismatch"

    workspace_a = settings.career_ops_workspace_root / str(seeded[0].id)
    (workspace_a / "output").mkdir(parents=True)
    (workspace_a / "output" / "a.pdf").write_bytes(b"private-a-pdf")
    async with sessions() as db:
        stored_cv = await db.get(TailoredCv, cv_a.id)
        stored_cv.artifact_key = "output/a.pdf"
        await db.commit()

    assert (await client.get(f"/api/v1/cvs/{cv_a.id}", headers=headers("clerk-b"))).status_code == 404
    assert (await client.get(f"/api/v1/cvs/{cv_b.id}", headers=headers("clerk-a"))).status_code == 404
    assert (await client.get(f"/api/v1/pipeline/evaluations/{evaluation_a.id}", headers=headers("clerk-b"))).status_code == 404
    assert (await client.get(f"/api/v1/pipeline/evaluations/{evaluation_b.id}", headers=headers("clerk-a"))).status_code == 404
    assert (await client.patch(f"/api/v1/pipeline/{candidate_a.id}", headers=headers("clerk-b"), json={"pipeline_status": "Interview"})).status_code == 404
    assert (await client.patch(f"/api/v1/pipeline/{candidate_b.id}", headers=headers("clerk-a"), json={"pipeline_status": "Interview"})).status_code == 404

    cv = (await client.get(f"/api/v1/cvs/{cv_a.id}", headers=headers("clerk-a"))).json()
    assert cv["source_html"] == "<html>Private A CV</html>"
    report = (await client.get(f"/api/v1/pipeline/evaluations/{evaluation_a.id}", headers=headers("clerk-a"))).json()
    assert report["report_markdown"] == "Private A report"
    assert (await client.get(f"/api/v1/cvs/{cv_a.id}/pdf", headers=headers("clerk-a"))).content == b"private-a-pdf"
    assert (await client.get(f"/api/v1/cvs/{cv_a.id}/pdf", headers=headers("clerk-b"))).status_code == 404
