"""Hosted (multi-user Munia) cheap triage (Phase 5 follow-up correction) —
candidate-specific Anthropic key/model, no CLI/subprocess. See
app.modules.pipeline.hosted_triage; automation.batch.triage_all/_run_agent
(the CLI-agent path) remains unchanged for local/single-user use.
"""

import uuid

import httpx

from app.core.crypto import generate_key
from app.modules.ai_config import service as ai_config_service
from app.modules.candidates.models import CandidateProfile, User
from app.modules.discovery import ai_search
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.hosted_triage import triage_candidate_hosted
from app.modules.pipeline.models import CandidateJob
from sqlalchemy import select


async def seed_user(sessions, clerk_user_id: str = "clerk-a", profile: dict | None = None) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, profile=profile or {"target_roles": {"primary": ["Director of Engineering"]}}))
        await db.commit()
        return user


async def make_candidate_job(sessions, user, *, title: str = "Director of Engineering", eligibility: str | None = None, triaged_at=None) -> tuple[CandidateJob, "Job"]:
    async with sessions() as db:
        payload = JobIngest(company="Acme", title=title, source="greenhouse", posting_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}", direct_application_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}")
        job, _, _ = await ingest_discovery(db, payload, method="reverse_ats")
        item = CandidateJob(user_id=user.id, job_id=job.id, eligibility=eligibility, triaged_at=triaged_at)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item, job


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


def fake_anthropic(text: str, status_code: int = 200):
    original_post = httpx.AsyncClient.post

    async def fake_post(self, url, *args, **kwargs):
        if str(url) != ai_search.ANTHROPIC_API_URL:
            return await original_post(self, url, *args, **kwargs)
        return httpx.Response(status_code, json={"content": [{"type": "text", "text": text}]}, request=httpx.Request("POST", url))

    return fake_post


async def configure_ai(client, clerk_user_id: str):
    await client.put("/api/v1/ai-config", headers=headers(clerk_user_id), json={"model": "claude-haiku-4-5-20251001", "api_key": f"sk-ant-{clerk_user_id}"})


async def test_hosted_triage_requires_no_cli(api, monkeypatch):
    """The whole point: no subprocess, no `claude` binary anywhere in this path."""
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic('{"result": "worth", "reason": "matches"}'))

    # No asyncio.create_subprocess_exec patch needed/present — if this path
    # tried to spawn a CLI, it would hang or raise in this sandbox with no
    # `claude` binary, and this call would simply fail.
    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user.id)
    assert result["status"] == "ok"
    assert result["triaged"] == 1


async def test_candidate_specific_anthropic_config_is_used(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    await make_candidate_job(sessions, user)

    seen_keys = []
    original_post = httpx.AsyncClient.post

    async def capture_post(self, url, *args, json=None, headers=None, **kwargs):
        if str(url) == ai_search.ANTHROPIC_API_URL:
            seen_keys.append(headers.get("x-api-key"))
            return httpx.Response(200, json={"content": [{"type": "text", "text": '{"result": "worth", "reason": "x"}'}]}, request=httpx.Request("POST", url))
        return await original_post(self, url, *args, json=json, headers=headers, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", capture_post)
    async with sessions() as db:
        await triage_candidate_hosted(db, settings, user.id)
    assert seen_keys == ["sk-ant-clerk-a"]


async def test_candidate_a_key_never_used_for_candidate_b(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user_a = await seed_user(sessions, "clerk-a")
    user_b = await seed_user(sessions, "clerk-b")
    await configure_ai(client, "clerk-a")
    # candidate B has NO AI configured
    await make_candidate_job(sessions, user_b)

    called = False

    async def fail_if_called(self, url, *args, **kwargs):
        nonlocal called
        if str(url) == ai_search.ANTHROPIC_API_URL:
            called = True
        raise AssertionError("should never reach Anthropic for an unconfigured candidate")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)
    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user_b.id)
    assert result["status"] == "skipped_not_configured"
    assert called is False


async def test_successful_triage_worth_stamps_triaged_at(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic('{"result": "worth", "reason": "great scope match"}'))

    async with sessions() as db:
        await triage_candidate_hosted(db, settings, user.id)
    async with sessions() as db:
        refreshed = await db.get(CandidateJob, item.id)
        assert refreshed.triage_result == "worth"
        assert refreshed.triage_reason == "great scope match"
        assert refreshed.triaged_at is not None


async def test_real_uncertain_stamps_triaged_at(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic('{"result": "uncertain", "reason": "needs a closer look"}'))

    async with sessions() as db:
        await triage_candidate_hosted(db, settings, user.id)
    async with sessions() as db:
        refreshed = await db.get(CandidateJob, item.id)
        assert refreshed.triage_result == "uncertain"
        assert refreshed.triaged_at is not None


async def test_malformed_response_does_not_stamp_triaged_at(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic("I think this role could be interesting but I'm rambling instead of returning JSON."))

    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user.id)
    assert result["triaged"] == 0
    async with sessions() as db:
        refreshed = await db.get(CandidateJob, item.id)
        assert refreshed.triaged_at is None
        assert refreshed.triage_result is None


async def test_invalid_key_does_not_stamp_triaged_at(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic("unauthorized", status_code=401))

    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user.id)
    assert result["status"] == "error"
    async with sessions() as db:
        refreshed = await db.get(CandidateJob, item.id)
        assert refreshed.triaged_at is None


async def test_rate_limit_does_not_stamp_triaged_at(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    item, job = await make_candidate_job(sessions, user)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic("rate limited", status_code=429))

    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user.id)
    assert result["status"] == "error"
    async with sessions() as db:
        refreshed = await db.get(CandidateJob, item.id)
        assert refreshed.triaged_at is None


async def test_no_ai_config_skips_cleanly_not_an_error(api):
    _, sessions, settings = api
    user = await seed_user(sessions)
    await make_candidate_job(sessions, user)
    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user.id)
    assert result["status"] == "skipped_not_configured"


async def test_location_ineligible_job_never_calls_triage_ai(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    # Already classified ineligible with triaged_at set (as apply_location_eligibility does)
    from datetime import datetime, timezone

    item, job = await make_candidate_job(sessions, user, eligibility="ineligible", triaged_at=datetime.now(timezone.utc))

    called = False

    async def fail_if_called(self, url, *args, **kwargs):
        nonlocal called
        if str(url) == ai_search.ANTHROPIC_API_URL:
            called = True
        raise AssertionError("must never call Anthropic for an ineligible/already-triaged job")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)
    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user.id)
    assert called is False
    assert result["triaged"] == 0


async def test_human_decided_job_never_calls_triage(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    item, job = await make_candidate_job(sessions, user)
    async with sessions() as db:
        db_item = await db.get(CandidateJob, item.id)
        db_item.pipeline_status = "Applied"
        await db.commit()

    called = False

    async def fail_if_called(self, url, *args, **kwargs):
        nonlocal called
        if str(url) == ai_search.ANTHROPIC_API_URL:
            called = True
        raise AssertionError("must never call Anthropic for a human-decided job")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)
    async with sessions() as db:
        await triage_candidate_hosted(db, settings, user.id)
    assert called is False


async def test_already_triaged_rediscovered_job_never_triaged_again(api, monkeypatch):
    from datetime import datetime, timezone

    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions)
    await configure_ai(client, "clerk-a")
    original_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item, job = await make_candidate_job(sessions, user, triaged_at=original_time)
    async with sessions() as db:
        db_item = await db.get(CandidateJob, item.id)
        db_item.triage_result = "worth"
        await db.commit()

    called = False

    async def fail_if_called(self, url, *args, **kwargs):
        nonlocal called
        if str(url) == ai_search.ANTHROPIC_API_URL:
            called = True
        raise AssertionError("must never re-triage an already-triaged job")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)
    async with sessions() as db:
        result = await triage_candidate_hosted(db, settings, user.id)
    assert called is False
    assert result["triaged"] == 0
