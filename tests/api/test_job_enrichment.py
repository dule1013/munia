"""Job-enrichment audit (#3811): Greenhouse/Lever/Ashby already return
description (and Greenhouse/Lever/Ashby now also an external posting id) for
free in the same list-API response the scan already makes — this preserves
it into the canonical Job instead of discarding it via data/pipeline.md's
lossy row format, without a second fetch and without ever overwriting a
richer existing field with a blank/weaker one.
"""

import uuid

from app.modules.automation import batch as automation_batch
from app.modules.automation.runner import CommandResult
from app.modules.jobs.models import Job


def make_job(**overrides) -> Job:
    defaults = dict(
        id=uuid.uuid4(),
        canonical_key=str(uuid.uuid4()),
        canonical_url="https://jobs.lever.co/acme/1",
        company="Acme",
        title="Staff Engineer",
        location="",
        description=None,
        source="lever",
        posting_url="https://jobs.lever.co/acme/1",
        is_active=True,
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_enrich_fills_description_location_posted_at_and_external_id():
    job = make_job()
    offers = [{
        "url": "https://jobs.lever.co/acme/1",
        "description": "Build the platform.",
        "location": "Remote — Europe",
        "postedAt": "2026-07-01",
        "externalId": "lever-abc-123",
    }]
    automation_batch.enrich_jobs_from_scan_json({job.posting_url: job}, offers)
    assert job.description == "Build the platform."
    assert job.location == "Remote — Europe"
    assert job.posted_at is not None and job.posted_at.year == 2026 and job.posted_at.month == 7 and job.posted_at.day == 1
    assert job.external_source_id == "lever-abc-123"


def test_enrich_never_overwrites_an_existing_richer_field_with_a_blank_or_weaker_one():
    job = make_job(description="Existing rich JD from a prior enrichment.", location="Madrid, Spain", external_source_id="already-set")
    offers = [{
        "url": "https://jobs.lever.co/acme/1",
        "description": "",  # a re-scan with no body this time must not erase the existing one
        "location": None,
        "externalId": "",
    }]
    automation_batch.enrich_jobs_from_scan_json({job.posting_url: job}, offers)
    assert job.description == "Existing rich JD from a prior enrichment."
    assert job.location == "Madrid, Spain"
    assert job.external_source_id == "already-set"


def test_enrich_matches_by_canonical_url_despite_markdown_escaping_differences():
    """data/pipeline.md's writer (scan.mjs sanitizePipelineUrl) escapes [ ] |
    for markdown and the JSON payload does not — a query-string ordering or
    trailing-slash difference must not prevent the match either."""
    job = make_job(posting_url="https://jobs.lever.co/acme/1?utm_source=x")
    offers = [{"url": "https://jobs.lever.co/acme/1/", "description": "JD text"}]
    automation_batch.enrich_jobs_from_scan_json({job.posting_url: job}, offers)
    assert job.description == "JD text"


def test_enrich_ignores_offers_with_no_matching_job():
    job = make_job()
    offers = [{"url": "https://jobs.lever.co/other-co/9", "description": "unrelated JD"}]
    automation_batch.enrich_jobs_from_scan_json({job.posting_url: job}, offers)
    assert job.description is None


def test_enrich_tolerates_empty_inputs():
    automation_batch.enrich_jobs_from_scan_json({}, [{"url": "https://x/1", "description": "d"}])
    automation_batch.enrich_jobs_from_scan_json({"https://x/1": make_job()}, [])
    automation_batch.enrich_jobs_from_scan_json({}, [])


def test_parse_json_offer_date_handles_missing_and_malformed_values():
    assert automation_batch._parse_json_offer_date(None) is None
    assert automation_batch._parse_json_offer_date("") is None
    assert automation_batch._parse_json_offer_date("not-a-date") is None
    parsed = automation_batch._parse_json_offer_date("2026-03-15")
    assert (parsed.year, parsed.month, parsed.day) == (2026, 3, 15)


async def test_rotating_reverse_discovery_enriches_the_imported_job_from_the_same_scan_json(api, monkeypatch):
    """End-to-end through rotating_reverse_discovery: import_pipeline (mocked
    to avoid real pipeline.md file I/O — its own dedicated tests cover
    parsing) returns the Job it just created/updated, and the description
    from the SAME subprocess's --json stdout must land on that exact row."""
    import json

    from tests.api.test_ats_rotation import seed_user_and_profile

    _, sessions, settings = api
    await seed_user_and_profile(sessions)

    async def fake_run_for_candidate(db, user_id, settings, script, *args, timeout=900):
        return CommandResult(0, json.dumps({
            "datasetSize": {"lever": 4368},
            "offers": [{"url": "https://jobs.lever.co/acme/1", "description": "Full JD from Lever.", "location": "Remote — Europe", "externalId": "lever-1"}],
        }), "")

    async def fake_import_pipeline(db, user, workspace, method=None, default_source=None):
        job = make_job(source=default_source or "lever")
        db.add(job)
        await db.flush()
        return {"https://jobs.lever.co/acme/1": job}

    monkeypatch.setattr(automation_batch, "run_for_candidate", fake_run_for_candidate)
    monkeypatch.setattr(automation_batch, "import_pipeline", fake_import_pipeline)

    async with sessions() as db:
        await automation_batch.rotating_reverse_discovery(db, settings, "lever", batch_size=1500)

    async with sessions() as db:
        job = await db.scalar(automation_batch.select(Job).where(Job.posting_url == "https://jobs.lever.co/acme/1"))
    assert job is not None
    assert job.description == "Full JD from Lever."
    assert job.location == "Remote — Europe"
    assert job.external_source_id == "lever-1"
