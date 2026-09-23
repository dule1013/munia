import uuid

import httpx
import pytest

from app.core.crypto import generate_key
from app.modules.ai_config import service as ai_config_service
from app.modules.candidates.models import User
from app.modules.discovery import ai_search
from app.modules.jobs.models import Job
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline import fit_assessment
from app.modules.pipeline.models import CandidateJob


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


async def make_candidate_job(sessions, user, *, title: str = "Director of Engineering") -> tuple[CandidateJob, Job]:
    async with sessions() as db:
        payload = JobIngest(company="Acme", title=title, source="greenhouse", posting_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}", direct_application_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}")
        job, _, _ = await ingest_discovery(db, payload, method="reverse_ats")
        item = CandidateJob(user_id=user.id, job_id=job.id, triage_result="worth")
        db.add(item)
        await db.commit()
        await db.refresh(item)
        await db.refresh(job)
        return item, job


def fake_response(text: str, status_code: int = 200):
    original_post = httpx.AsyncClient.post

    async def fake_post(self, url, *args, **kwargs):
        if str(url) != ai_search.ANTHROPIC_API_URL:
            return await original_post(self, url, *args, **kwargs)
        return httpx.Response(status_code, json={"content": [{"type": "text", "text": text}]}, request=httpx.Request("POST", url))

    return fake_post


STRONG_RESPONSE = '{"fit": "strong", "reason": "Exact match for Director-level scope.", "confidence": "high"}'


async def test_no_ai_configured_raises(api):
    _, sessions, settings = api
    user = await seed_user(sessions)
    item, job = await make_candidate_job(sessions, user)
    async with sessions() as db:
        with pytest.raises(fit_assessment.NoAIConfigured):
            await fit_assessment.assess_fit(db, settings, item, job)


async def test_structured_strong_result_parsed_and_applied(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": user.clerk_user_id}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_response(STRONG_RESPONSE))

    async with sessions() as db:
        item = await db.get(CandidateJob, item.id)
        assessment = await fit_assessment.assess_fit(db, settings, item, job)
        assert assessment == {"fit": "strong", "reason": "Exact match for Director-level scope.", "confidence": "high"}
        await fit_assessment.apply_assessment(db, item, assessment)
        await db.commit()
        await db.refresh(item)
    assert item.ai_fit == "strong"
    assert item.ai_fit_confidence == "high"
    assert item.ai_fit_assessed_at is not None
    # Never touches the full-evaluate fields.
    assert item.fit_score is None
    assert item.evaluated_at is None


async def test_low_confidence_strong_is_downgraded_to_plausible(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": user.clerk_user_id}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    item, job = await make_candidate_job(sessions, user)
    text = '{"fit": "strong", "reason": "Might fit.", "confidence": "low"}'
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_response(text))

    async with sessions() as db:
        item = await db.get(CandidateJob, item.id)
        assessment = await fit_assessment.assess_fit(db, settings, item, job)
        await fit_assessment.apply_assessment(db, item, assessment)
        await db.commit()
        await db.refresh(item)
    assert item.ai_fit == "plausible"


async def test_malformed_model_output_returns_none(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": user.clerk_user_id}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_response("I think this is a decent role but I'm not sure."))

    async with sessions() as db:
        item = await db.get(CandidateJob, item.id)
        assessment = await fit_assessment.assess_fit(db, settings, item, job)
    assert assessment is None


async def test_api_failure_returns_none(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": user.clerk_user_id}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_response("unauthorized", status_code=401))

    async with sessions() as db:
        item = await db.get(CandidateJob, item.id)
        assessment = await fit_assessment.assess_fit(db, settings, item, job)
    assert assessment is None


async def test_reject_does_not_remove_existing_human_visible_candidate_job(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": user.clerk_user_id}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    item, job = await make_candidate_job(sessions, user)

    async with sessions() as db:
        item = await db.get(CandidateJob, item.id)
        await fit_assessment.apply_assessment(db, item, {"fit": "reject", "reason": "Not a fit.", "confidence": "high"})
        await db.commit()
        await db.refresh(item)
    assert item.ai_fit == "reject"
    assert item.pipeline_status == "Inbox"  # still exists, still in Inbox's default state — not deleted


async def test_apply_assessment_skips_a_candidate_job_the_human_already_decided(api):
    _, sessions, settings = api
    user = await seed_user(sessions)
    item, job = await make_candidate_job(sessions, user)

    async with sessions() as db:
        item = await db.get(CandidateJob, item.id)
        item.pipeline_status = "Applied"
        await db.commit()
        await fit_assessment.apply_assessment(db, item, {"fit": "strong", "reason": "x", "confidence": "high"})
        await db.commit()
        await db.refresh(item)
    assert item.ai_fit is None  # untouched — human already moved this job


async def test_assessment_uses_the_owning_candidates_own_key_not_anyone_elses(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user_a = await seed_user(sessions, "clerk-a")
    user_b = await seed_user(sessions, "clerk-b")
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": "clerk-a"}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-a-secret"})

    item_b, job_b = await make_candidate_job(sessions, user_b)
    async with sessions() as db:
        item_b = await db.get(CandidateJob, item_b.id)
        with pytest.raises(fit_assessment.NoAIConfigured):
            await fit_assessment.assess_fit(db, settings, item_b, job_b)


def test_parse_assessment_rejects_invalid_fit_or_confidence_values():
    assert fit_assessment.parse_assessment('{"fit": "amazing", "reason": "x", "confidence": "high"}') is None
    assert fit_assessment.parse_assessment('{"fit": "strong", "reason": "x", "confidence": "medium"}') is None
    assert fit_assessment.parse_assessment("not json at all") is None
    assert fit_assessment.parse_assessment('{"fit": "reject", "reason": "x", "confidence": "low"}') == {"fit": "reject", "reason": "x", "confidence": "low"}
