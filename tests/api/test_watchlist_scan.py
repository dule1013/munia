import uuid

import pytest
import yaml
from sqlalchemy import select

from app.modules.automation.runner import CommandResult
from app.modules.automation.batch import watchlist_all
from app.modules.candidates.models import CandidateProfile, User
from app.modules.discovery import watchlist_scan
from app.modules.discovery.watchlist_service import create_watched_company
from app.modules.discovery.watchlist_schemas import WatchedCompanyCreate
from app.modules.jobs.models import Job, JobDiscovery
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.models import CandidateJob

EMPTY_PIPELINE = "# Pipeline — Pending URLs\n\n## Pending\n\n## Processed\n"


@pytest.fixture(autouse=True)
def no_real_engine_symlinks(monkeypatch):
    """These tests mock run_in_workspace itself, so the shared workspace
    never needs a real providers/scan.mjs symlink tree — only a plain
    directory with a data/ subfolder for the fake to write pipeline.md into."""

    def fake_ensure_system_layer(workspace, settings):
        (workspace / "data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(watchlist_scan, "ensure_system_layer", fake_ensure_system_layer)


def pipeline_row(url: str, company: str, title: str, location: str) -> str:
    return f"- [ ] {url} | {company} | {title} | {location}"


def fake_run_in_workspace(rows_by_company: dict[str, list[str]], failing_companies: frozenset[str] = frozenset()):
    async def fake(workspace, settings, script, *args, timeout=900):
        assert script == "scan.mjs"
        config = yaml.safe_load((workspace / "portals.yml").read_text(encoding="utf-8")) or {}
        company_name = (config.get("tracked_companies") or [{}])[0].get("name", "")
        if company_name in failing_companies:
            return CommandResult(1, "", f"provider error scanning {company_name}")
        rows = rows_by_company.get(company_name, [])
        pipeline_text = EMPTY_PIPELINE.replace("## Pending\n\n", "## Pending\n\n" + "\n".join(rows) + ("\n" if rows else "") + "\n") if rows else EMPTY_PIPELINE
        (workspace / "data" / "pipeline.md").write_text(pipeline_text, encoding="utf-8")
        return CommandResult(0, "{}", "")

    return fake


async def seed_user_with_profile(sessions, clerk_user_id: str, *, target_roles: list[str] | None = None) -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        profile = {"target_roles": {"primary": target_roles}} if target_roles else {}
        db.add(CandidateProfile(user_id=user.id, profile=profile))
        await db.commit()
        return user


def headers(user: str) -> dict[str, str]:
    return {"x-test-clerk-user-id": user}


async def add_watchlist(client, user_header: str, *, company_name: str, careers_url: str) -> dict:
    resp = await client.post("/api/v1/discovery/watchlist", headers=headers(user_header), json={"company_name": company_name, "careers_url": careers_url})
    assert resp.status_code == 201
    return resp.json()


async def test_unsupported_provider_is_skipped_without_scanning(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a")
    await add_watchlist(client, "clerk-a", company_name="Mystery Co", careers_url="https://careers.example.com/mystery")

    call_count = {"n": 0}

    async def counting_fake(*args, **kwargs):
        call_count["n"] += 1
        return CommandResult(0, "{}", "")

    monkeypatch.setattr(watchlist_scan, "run_in_workspace", counting_fake)

    async with sessions() as db:
        result = await watchlist_scan.run_watchlist_scan(db, settings)

    assert result["unsupported_provider"] == 1
    assert result["scanned_ok"] == 0
    assert call_count["n"] == 0

    async with sessions() as db:
        jobs = list(await db.scalars(select(Job)))
        assert jobs == []


async def test_shared_company_scanned_once_for_two_candidates(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a", target_roles=["Director of Engineering"])
    await seed_user_with_profile(sessions, "clerk-b", target_roles=["Director of Engineering"])
    await add_watchlist(client, "clerk-a", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")
    await add_watchlist(client, "clerk-b", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")

    call_count = {"n": 0}
    rows = {"Docplanner": [pipeline_row("https://jobs.ashbyhq.com/docplanner/1", "Docplanner", "Director of Engineering", "Remote")]}
    base_fake = fake_run_in_workspace(rows)

    async def counting_fake(*args, **kwargs):
        call_count["n"] += 1
        return await base_fake(*args, **kwargs)

    monkeypatch.setattr(watchlist_scan, "run_in_workspace", counting_fake)

    async with sessions() as db:
        result = await watchlist_scan.run_watchlist_scan(db, settings)

    assert call_count["n"] == 1  # scanned once, not once per watcher
    assert result["scanned_ok"] == 1
    assert result["jobs_created"] == 1
    assert result["candidate_jobs_created"] == 2

    async with sessions() as db:
        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1
        assert jobs[0].source == "ashby"

        discovery = await db.scalar(select(JobDiscovery).where(JobDiscovery.job_id == jobs[0].id))
        assert discovery.method == "company_watchlist"
        assert discovery.source == "ashby"
        assert discovery.source_url == jobs[0].canonical_url

        candidate_jobs = list(await db.scalars(select(CandidateJob).where(CandidateJob.job_id == jobs[0].id)))
        assert len(candidate_jobs) == 2


async def test_relevance_filter_still_applies_within_watchers(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a", target_roles=["Director of Engineering"])
    await seed_user_with_profile(sessions, "clerk-b", target_roles=["Solutions Architect"])  # won't match
    await add_watchlist(client, "clerk-a", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")
    await add_watchlist(client, "clerk-b", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")

    rows = {"Docplanner": [pipeline_row("https://jobs.ashbyhq.com/docplanner/1", "Docplanner", "Director of Engineering", "Remote")]}
    monkeypatch.setattr(watchlist_scan, "run_in_workspace", fake_run_in_workspace(rows))

    async with sessions() as db:
        result = await watchlist_scan.run_watchlist_scan(db, settings)

    assert result["candidate_jobs_created"] == 1  # only clerk-a matches

    async with sessions() as db:
        job = await db.scalar(select(Job))
        candidate_jobs = list(await db.scalars(select(CandidateJob).where(CandidateJob.job_id == job.id)))
        assert len(candidate_jobs) == 1


async def test_non_watcher_never_receives_candidate_job(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a", target_roles=["Director of Engineering"])
    await seed_user_with_profile(sessions, "clerk-c", target_roles=["Director of Engineering"])  # matches, but doesn't watch
    await add_watchlist(client, "clerk-a", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")

    rows = {"Docplanner": [pipeline_row("https://jobs.ashbyhq.com/docplanner/1", "Docplanner", "Director of Engineering", "Remote")]}
    monkeypatch.setattr(watchlist_scan, "run_in_workspace", fake_run_in_workspace(rows))

    async with sessions() as db:
        await watchlist_scan.run_watchlist_scan(db, settings)

    async with sessions() as db:
        job = await db.scalar(select(Job))
        candidate_jobs = list(await db.scalars(select(CandidateJob).where(CandidateJob.job_id == job.id)))
        assert len(candidate_jobs) == 1  # clerk-a only, not clerk-c


async def test_disabled_watched_company_is_skipped(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a")
    created = await add_watchlist(client, "clerk-a", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")
    await client.patch(f"/api/v1/discovery/watchlist/{created['id']}", headers=headers("clerk-a"), json={"enabled": False})

    called = {"n": 0}

    async def counting_fake(*args, **kwargs):
        called["n"] += 1
        return CommandResult(0, "{}", "")

    monkeypatch.setattr(watchlist_scan, "run_in_workspace", counting_fake)

    async with sessions() as db:
        result = await watchlist_scan.run_watchlist_scan(db, settings)

    assert result["targets"] == 0
    assert called["n"] == 0


async def test_one_companys_provider_failure_does_not_abort_others(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a", target_roles=["Director of Engineering"])
    await add_watchlist(client, "clerk-a", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")
    await add_watchlist(client, "clerk-a", company_name="Snyk", careers_url="https://jobs.ashbyhq.com/snyk")

    rows = {"Docplanner": [pipeline_row("https://jobs.ashbyhq.com/docplanner/1", "Docplanner", "Director of Engineering", "Remote")]}
    monkeypatch.setattr(watchlist_scan, "run_in_workspace", fake_run_in_workspace(rows, failing_companies=frozenset({"Snyk"})))

    async with sessions() as db:
        result = await watchlist_scan.run_watchlist_scan(db, settings)

    assert result["scanned_ok"] == 1
    assert result["failed"] == 1
    assert result["jobs_created"] == 1

    async with sessions() as db:
        from app.modules.discovery.models import WatchedCompany

        entries = {row.company_name: row for row in await db.scalars(select(WatchedCompany))}
        assert entries["Docplanner"].scan_status == "ok"
        assert entries["Docplanner"].last_scan_error is None
        assert entries["Snyk"].scan_status == "error"
        assert "provider error scanning Snyk" in entries["Snyk"].last_scan_error
        assert entries["Docplanner"].last_scanned_at is not None
        assert entries["Snyk"].last_scanned_at is not None


async def test_watchlist_job_dedups_against_existing_reverse_ats_job(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a", target_roles=["Director of Engineering"])
    await add_watchlist(client, "clerk-a", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")

    async with sessions() as db:
        existing_job, _, _ = await ingest_discovery(db, JobIngest(company="Docplanner", title="Director of Engineering", location="Remote", source="ashby", posting_url="https://jobs.ashbyhq.com/docplanner/1", direct_application_url="https://jobs.ashbyhq.com/docplanner/1"), method="reverse_ats")
        await db.commit()
        existing_job_id = existing_job.id

    rows = {"Docplanner": [pipeline_row("https://jobs.ashbyhq.com/docplanner/1", "Docplanner", "Director of Engineering", "Remote")]}
    monkeypatch.setattr(watchlist_scan, "run_in_workspace", fake_run_in_workspace(rows))

    async with sessions() as db:
        result = await watchlist_scan.run_watchlist_scan(db, settings)

    assert result["jobs_created"] == 0  # attached to the existing reverse-ATS job

    async with sessions() as db:
        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1
        assert jobs[0].id == existing_job_id
        discoveries = list(await db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == existing_job_id)))
        assert {d.method for d in discoveries} == {"reverse_ats", "company_watchlist"}


async def test_watchlist_job_dedups_against_existing_linkedin_job(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a", target_roles=["Director of Engineering"])
    await add_watchlist(client, "clerk-a", company_name="Docplanner", careers_url="https://jobs.ashbyhq.com/docplanner")

    async with sessions() as db:
        linkedin_job, _, _ = await ingest_discovery(db, JobIngest(company="Docplanner", title="Director of Engineering", location="", source="linkedin", posting_url="https://www.linkedin.com/jobs/view/999888777", direct_application_url="https://www.linkedin.com/jobs/view/999888777"), method="email_alert")
        await db.commit()
        linkedin_job_id = linkedin_job.id

    rows = {"Docplanner": [pipeline_row("https://jobs.ashbyhq.com/docplanner/1", "Docplanner", "Director of Engineering", "")]}
    monkeypatch.setattr(watchlist_scan, "run_in_workspace", fake_run_in_workspace(rows))

    async with sessions() as db:
        result = await watchlist_scan.run_watchlist_scan(db, settings)

    assert result["jobs_created"] == 0  # the strong ashby observation upgrades the weak linkedin Job

    async with sessions() as db:
        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1
        assert jobs[0].id == linkedin_job_id
        assert jobs[0].source == "ashby"
        discoveries = list(await db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == linkedin_job_id)))
        assert {d.source for d in discoveries} == {"linkedin", "ashby"}


async def test_watchlist_all_automation_wrapper_delegates(api, monkeypatch):
    client, sessions, settings = api
    await seed_user_with_profile(sessions, "clerk-a")

    async def counting_fake(*args, **kwargs):
        return CommandResult(0, "{}", "")

    monkeypatch.setattr(watchlist_scan, "run_in_workspace", counting_fake)
    async with sessions() as db:
        result = await watchlist_all(db, settings)
    assert result["targets"] == 0
