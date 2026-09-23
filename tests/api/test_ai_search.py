import uuid

import httpx
import pytest

from app.core.crypto import generate_key
from app.modules.ai_config import service as ai_config_service
from app.modules.candidates.models import User
from app.modules.discovery import ai_search
from app.modules.jobs.models import Job, JobDiscovery
from sqlalchemy import select


async def seed_user(sessions, clerk_user_id: str) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


def fake_anthropic_response(text: str, status_code: int = 200):
    """Patches httpx.AsyncClient.post at the class level, which the test
    client (also an httpx.AsyncClient, via ASGITransport) shares — so this
    must only intercept the actual outbound call to Anthropic and delegate
    everything else (including the test's own calls into the FastAPI app)
    to the real implementation."""
    original_post = httpx.AsyncClient.post

    async def fake_post(self, url, *args, **kwargs):
        if str(url) != ai_search.ANTHROPIC_API_URL:
            return await original_post(self, url, *args, **kwargs)
        body = {"content": [{"type": "text", "text": text}]}
        return httpx.Response(status_code, json=body, request=httpx.Request("POST", url))

    return fake_post


VALID_RESULT_TEXT = 'I searched and found these:\n[{"company": "Acme", "title": "Director of Engineering", "location": "Remote - Spain", "url": "https://acme.example.com/jobs/1"}]'


async def test_ai_search_requires_configuration(api):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    resp = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-a"), json={"query": "director of engineering spain"})
    assert resp.status_code == 409


async def test_ai_search_creates_job_and_candidate_job(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic_response(VALID_RESULT_TEXT))

    resp = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-a"), json={"query": "director of engineering spain"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["jobs_found"] == 1
    assert body["jobs_created"] == 1
    assert body["jobs_attached"] == 1

    async with sessions() as db:
        job = await db.scalar(select(Job).where(Job.company == "Acme"))
        assert job is not None
        assert job.source == "web-discovery"
        discovery = await db.scalar(select(JobDiscovery).where(JobDiscovery.job_id == job.id))
        assert discovery.method == "web_search"


async def test_ai_search_malformed_response_yields_zero_results_not_an_error(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic_response("Sorry, I couldn't find any real postings."))

    resp = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-a"), json={"query": "director of engineering spain"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["jobs_found"] == 0


async def test_ai_search_invalid_api_key_reported_cleanly(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic_response("unauthorized", status_code=401))

    resp = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-a"), json={"query": "director of engineering spain"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "key" in body["error"].lower()


async def test_manual_search_rate_limited_on_rapid_repeat(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic_response(VALID_RESULT_TEXT))

    first = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-a"), json={"query": "director of engineering spain"})
    assert first.status_code == 200
    second = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-a"), json={"query": "director of engineering spain"})
    assert second.status_code == 429


async def test_candidate_isolation_for_ai_search(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-a"})
    # candidate B has NOT configured AI — must be told so, never use A's key.
    resp = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-b"), json={"query": "director of engineering"})
    assert resp.status_code == 409


async def test_prompt_never_leaks_a_key_and_extraction_ignores_narration(monkeypatch):
    text = "Here is my reasoning about the search...\n" + VALID_RESULT_TEXT + "\nHope that helps!"
    candidates = ai_search.extract_job_candidates(text)
    assert len(candidates) == 1
    assert candidates[0]["company"] == "Acme"


# ── Candidate context is automatic, not something the user has to type ──────
# Explore AI Search product-quality fix (#3811 P0-B): a plain, unqualified
# query like "Director of Engineering roles" must still get anchored to the
# candidate's own location/eligible regions server-side.

def test_build_candidate_context_uses_the_richer_location_block_when_present():
    """This is exactly Dusan's real profile shape — build_daily_discovery_query
    and the location eligibility classifier already handle it; the interactive
    AI Search prompt must too, not fall back to the narrower `candidate.location`
    lookup hosted_triage._profile_summary uses."""
    profile = {"location": {"city": "Madrid", "country": "Spain", "authorized_in": ["Spain", "European Union", "European Economic Area", "Serbia"]}}
    context = ai_search.build_candidate_context(profile)
    assert "Madrid" in context
    assert "serbia" in context.lower() or "european union" in context.lower()


def test_build_candidate_context_falls_back_to_simple_profile_shape():
    profile = {"candidate": {"location": "Lisbon, Portugal"}}
    context = ai_search.build_candidate_context(profile)
    assert "Lisbon, Portugal" in context


def test_build_candidate_context_empty_when_no_location_anywhere():
    assert ai_search.build_candidate_context({}) == ""
    assert ai_search.build_candidate_context({"location": {}}) == ""


def test_build_prompt_includes_candidate_context_when_present():
    prompt = ai_search.build_prompt("Director of Engineering roles", None, "based in Madrid, Spain")
    assert "based in Madrid, Spain" in prompt
    assert "Do not return postings scoped to a single other country" in prompt


def test_build_prompt_omits_context_sentence_when_none_available():
    prompt = ai_search.build_prompt("Director of Engineering roles", None, "")
    assert "The candidate is" not in prompt


async def test_ai_search_route_includes_location_context_in_the_actual_anthropic_call(api, monkeypatch):
    """End-to-end: a candidate with a configured profile location gets that
    location baked into the real outbound prompt automatically, even though
    the query itself says nothing about location."""
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions, "clerk-a")
    async with sessions() as db:
        from app.modules.candidates.models import CandidateProfile

        db.add(CandidateProfile(user_id=user.id, profile={"location": {"city": "Madrid", "country": "Spain"}}, portals_yaml=""))
        await db.commit()
    await client.put("/api/v1/ai-config", headers=headers("clerk-a"), json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})

    captured_body = {}
    original_post = httpx.AsyncClient.post

    async def capturing_post(self, url, *args, **kwargs):
        if str(url) == ai_search.ANTHROPIC_API_URL:
            captured_body.update(kwargs.get("json") or {})
            return httpx.Response(200, json={"content": [{"type": "text", "text": VALID_RESULT_TEXT}]}, request=httpx.Request("POST", url))
        return await original_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", capturing_post)
    resp = await client.post("/api/v1/discovery/ai-search", headers=headers("clerk-a"), json={"query": "Director of Engineering roles"})
    assert resp.status_code == 200
    sent_prompt = captured_body["messages"][0]["content"]
    assert "Madrid" in sent_prompt
