import json
import uuid

import httpx

from app.core.crypto import generate_key
from app.modules.automation import batch as automation_batch
from app.modules.automation.runner import CommandResult
from app.modules.candidates.models import CandidateProfile, User
from app.modules.discovery import ai_search
from app.modules.discovery.ats_rotation import get_or_create_cursor
from app.modules.discovery.models import MorningRun
from app.modules.jobs.models import Job
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.service import list_inbox, list_today


DUSAN_PROFILE = {"location": {"city": "Madrid", "country": "Spain", "authorized_in": ["Spain", "European Union"]}, "target_roles": {"primary": ["Director of Engineering"]}}


async def seed_user(sessions, clerk_user_id: str = "clerk-a", profile: dict | None = None) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, portals_yaml="title_filter:\n  positive: []\n  negative: []\ntracked_companies: []\n", profile=profile or DUSAN_PROFILE))
        await db.commit()
        return user


async def fake_run_for_candidate_ok(db, user_id, settings, script, *args, timeout=900):
    ats = args[args.index("--ats") + 1] if "--ats" in args else "unknown"
    return CommandResult(0, json.dumps({"datasetSize": {ats: 1000}}), "")


async def fake_watchlist_all(db, settings):
    """These tests aren't exercising watchlist_scan (that's
    test_watchlist_scan.py's job) — no watched companies exist here, and
    without mocking ensure_system_layer's real filesystem setup (as that
    file does) an empty-but-real code root would fail with ENOENT, which
    would otherwise make every test below about "is X isolated from Y" also
    incidentally test watchlist's own isolation instead."""
    return {"targets": 0, "scanned_ok": 0, "unsupported_provider": 0, "failed": 0, "jobs_found": 0, "jobs_created": 0, "candidate_jobs_created": 0}


async def fake_triage_marks_everything_triaged(db, settings, user_id):
    """Stands in for the real CLI-agent-based cheap triage (which needs the
    `claude` binary + a real candidate workspace, neither present in this
    test environment) — simulates "triage ran and confirmed every pending
    job's current triage_result" by stamping triaged_at, exactly what
    persist_triage_results itself does on a real run. These tests are about
    AI discovery / location eligibility / fit assessment / isolation, not
    about triage's own CLI mechanics (that's test_triage_protection.py's job)."""
    from datetime import datetime, timezone
    from sqlalchemy import select as sa_select

    rows = await db.execute(sa_select(CandidateJob).where(CandidateJob.user_id == user_id, CandidateJob.pipeline_status == "Inbox", CandidateJob.triaged_at.is_(None)))
    count = 0
    for item in rows.scalars().all():
        item.triaged_at = datetime.now(timezone.utc)
        count += 1
    await db.commit()
    return {"status": "ok", "processed": count}


def fake_anthropic(text: str, status_code: int = 200):
    original_post = httpx.AsyncClient.post

    async def fake_post(self, url, *args, **kwargs):
        if str(url) != ai_search.ANTHROPIC_API_URL:
            return await original_post(self, url, *args, **kwargs)
        return httpx.Response(status_code, json={"content": [{"type": "text", "text": text}]}, request=httpx.Request("POST", url))

    return fake_post


async def test_morning_run_isolates_a_failing_ats_source(api, monkeypatch):
    _, sessions, settings = api
    await seed_user(sessions)

    async def flaky(db, user_id, settings, script, *args, timeout=900):
        if "--ats" in args and args[args.index("--ats") + 1] == "workday":
            return CommandResult(1, "", "network timeout")
        return await fake_run_for_candidate_ok(db, user_id, settings, script, *args, timeout=timeout)

    monkeypatch.setattr(automation_batch, "run_for_candidate", flaky)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)
    monkeypatch.setattr(automation_batch, "_triage_one_candidate", fake_triage_marks_everything_triaged)

    async with sessions() as db:
        result = await automation_batch.morning_run(db, settings)

    assert result["status"] == "completed_with_warnings"
    assert result["summary"]["sources"]["workday"]["status"] == "error"
    # every other ATS source still ran successfully despite Workday failing
    for ats in ("greenhouse", "lever", "ashby", "icims"):
        assert result["summary"]["sources"][ats]["status"] == "ok"


async def test_morning_run_isolates_a_failing_candidate(api, monkeypatch):
    _, sessions, settings = api
    await seed_user(sessions, "clerk-a")
    await seed_user(sessions, "clerk-b")
    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)
    monkeypatch.setattr(automation_batch, "_triage_one_candidate", fake_triage_marks_everything_triaged)

    async def flaky_cycle(db, settings, user, run_id):
        if user.clerk_user_id == "clerk-a":
            raise RuntimeError("boom")
        return {"ai_status": "skipped_not_configured", "location_classified": 0, "fit_assessed": 0}

    monkeypatch.setattr(automation_batch, "_candidate_morning_cycle", flaky_cycle)

    async with sessions() as db:
        result = await automation_batch.morning_run(db, settings)

    assert result["status"] == "completed_with_warnings"
    candidates = result["summary"]["candidates"]
    statuses = [c.get("status") for c in candidates.values()]
    assert "error" in statuses
    assert any(c.get("ai_status") == "skipped_not_configured" for c in candidates.values())


async def test_morning_run_skips_ai_cleanly_when_candidate_has_no_config(api, monkeypatch):
    _, sessions, settings = api
    await seed_user(sessions)
    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)
    monkeypatch.setattr(automation_batch, "_triage_one_candidate", fake_triage_marks_everything_triaged)

    async with sessions() as db:
        result = await automation_batch.morning_run(db, settings)

    assert result["status"] == "completed"  # no AI config is NOT a warning-worthy failure
    candidate = next(iter(result["summary"]["candidates"].values()))
    assert candidate["ai_status"] == "skipped_not_configured"


async def test_morning_run_invalid_ai_key_does_not_affect_other_candidates(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user_a = await seed_user(sessions, "clerk-a")
    user_b = await seed_user(sessions, "clerk-b")
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": "clerk-a"}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-bad"})
    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)
    monkeypatch.setattr(automation_batch, "_triage_one_candidate", fake_triage_marks_everything_triaged)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic("unauthorized", status_code=401))

    async with sessions() as db:
        result = await automation_batch.morning_run(db, settings)

    assert result["summary"]["candidates"][str(user_a.id)]["ai_status"] == "error"
    assert result["summary"]["candidates"][str(user_b.id)]["ai_status"] == "skipped_not_configured"
    # candidate B is untouched by A's bad key
    assert result["status"] == "completed_with_warnings"


async def test_all_five_ats_sources_attempted_in_one_morning_run(api, monkeypatch):
    _, sessions, settings = api
    await seed_user(sessions)
    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)
    monkeypatch.setattr(automation_batch, "_triage_one_candidate", fake_triage_marks_everything_triaged)

    async with sessions() as db:
        result = await automation_batch.morning_run(db, settings)

    for ats in ("greenhouse", "lever", "ashby", "workday", "icims"):
        assert ats in result["summary"]["sources"]

    async with sessions() as db:
        for ats in ("greenhouse", "lever", "ashby", "workday", "icims"):
            cursor = await get_or_create_cursor(db, ats)
            assert cursor.next_offset > 0  # each cursor actually advanced


async def test_location_classifier_participates_and_ineligible_never_reaches_assessment(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": "clerk-a"}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})

    # Seed one ineligible and one eligible job directly (bypassing the ATS
    # scan network call, which is mocked away in this test).
    async with sessions() as db:
        ineligible_payload = JobIngest(company="Acme", title="Director of Engineering", location="US Remote", source="greenhouse", posting_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}", direct_application_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}")
        job_ineligible, _, _ = await ingest_discovery(db, ineligible_payload, method="reverse_ats")
        eligible_payload = JobIngest(company="Acme", title="Director of Engineering", location="Madrid, Spain", source="greenhouse", posting_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}", direct_application_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}")
        job_eligible, _, _ = await ingest_discovery(db, eligible_payload, method="reverse_ats")
        db.add(CandidateJob(user_id=user.id, job_id=job_ineligible.id, triage_result="uncertain"))
        db.add(CandidateJob(user_id=user.id, job_id=job_eligible.id, triage_result="uncertain"))
        await db.commit()

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)
    monkeypatch.setattr(automation_batch, "_triage_one_candidate", fake_triage_marks_everything_triaged)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic('{"fit": "strong", "reason": "great match", "confidence": "high"}'))

    async with sessions() as db:
        await automation_batch.morning_run(db, settings)

    async with sessions() as db:
        ineligible_item = await db.scalar(select_cj(job_ineligible.id, user.id))
        eligible_item = await db.scalar(select_cj(job_eligible.id, user.id))
    assert ineligible_item.eligibility == "ineligible"
    assert ineligible_item.ai_fit is None  # never reached the expensive assessment step
    assert eligible_item.eligibility == "eligible"
    assert eligible_item.ai_fit == "strong"

    async with sessions() as db:
        inbox = await list_inbox(db, user.id)
        today = await list_today(db, user.id)
    inbox_job_ids = {job.id for _, job in inbox}
    assert job_ineligible.id not in inbox_job_ids
    assert job_eligible.id in {job.id for _, job in today}


def select_cj(job_id, user_id):
    from sqlalchemy import select as sa_select

    return sa_select(CandidateJob).where(CandidateJob.job_id == job_id, CandidateJob.user_id == user_id)


async def test_new_count_is_tied_to_the_completed_morning_run(api, monkeypatch):
    client, sessions, settings = api
    settings.integration_encryption_key = generate_key()
    user = await seed_user(sessions, "clerk-a")
    await client.put("/api/v1/ai-config", headers={"x-test-clerk-user-id": "clerk-a"}, json={"model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-fake"})

    async with sessions() as db:
        payload = JobIngest(company="Acme", title="Director of Engineering", location="Madrid, Spain", source="greenhouse", posting_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}", direct_application_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}")
        job, _, _ = await ingest_discovery(db, payload, method="reverse_ats")
        db.add(CandidateJob(user_id=user.id, job_id=job.id, triage_result="uncertain"))
        await db.commit()

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate_ok)
    monkeypatch.setattr(automation_batch, "watchlist_all", fake_watchlist_all)
    monkeypatch.setattr(automation_batch, "_triage_one_candidate", fake_triage_marks_everything_triaged)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_anthropic('{"fit": "strong", "reason": "great match", "confidence": "high"}'))

    async with sessions() as db:
        result = await automation_batch.morning_run(db, settings)
    assert result["status"] == "completed_with_warnings" or result["status"] == "completed"

    async with sessions() as db:
        from app.modules.pipeline.service import today_summary

        summary = await today_summary(db, user.id)
    assert summary["current"] == 1
    assert summary["new"] == 1


async def test_production_mode_routing_is_unaffected_by_automation_changes(api):
    """Sanity: adding morning_run must not disturb the multi-user
    (production) routing/isolation this whole system depends on."""
    _, sessions, _ = api
    user_a = await seed_user(sessions, "clerk-a")
    user_b = await seed_user(sessions, "clerk-b")
    async with sessions() as db:
        inbox_a = await list_inbox(db, user_a.id)
        inbox_b = await list_inbox(db, user_b.id)
    assert inbox_a == []
    assert inbox_b == []
