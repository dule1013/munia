import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.modules.jobs.models import Job, JobDiscovery
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery, normalize_title, record_job_discovery


def linkedin_offer(**overrides) -> JobIngest:
    defaults = dict(company="Acme Corp", title="Director of Engineering", location="Madrid, Spain", source="linkedin", posting_url="https://www.linkedin.com/jobs/view/123456", direct_application_url="https://www.linkedin.com/jobs/view/123456")
    defaults.update(overrides)
    return JobIngest(**defaults)


def greenhouse_offer(**overrides) -> JobIngest:
    defaults = dict(company="Acme Corp", title="Director of Engineering", location="Madrid, Spain", source="greenhouse", posting_url="https://job-boards.greenhouse.io/acme/jobs/456", direct_application_url="https://job-boards.greenhouse.io/acme/jobs/456", external_source_id="456")
    defaults.update(overrides)
    return JobIngest(**defaults)


async def test_greenhouse_first_then_linkedin_resolves_to_one_job_with_two_discoveries(api):
    _, sessions, _ = api
    async with sessions() as db:
        job1, discovery1, created1 = await ingest_discovery(db, greenhouse_offer(), method="reverse_ats")
        await db.commit()
        job2, discovery2, created2 = await ingest_discovery(db, linkedin_offer(), method="email_alert", user_id=uuid.uuid4())
        await db.commit()

        assert created1 is True
        assert created2 is False
        assert job1.id == job2.id
        # The weak LinkedIn observation must never overwrite the strong canonical identity.
        assert job2.source == "greenhouse"
        assert job2.canonical_url.endswith("/acme/jobs/456")

        discoveries = list(await db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == job1.id)))
        assert {d.source for d in discoveries} == {"greenhouse", "linkedin"}
        assert {d.method for d in discoveries} == {"reverse_ats", "email_alert"}
        assert discovery1.id != discovery2.id


async def test_linkedin_first_then_greenhouse_upgrades_canonical_job(api):
    _, sessions, _ = api
    async with sessions() as db:
        job1, _, created1 = await ingest_discovery(db, linkedin_offer(), method="email_alert")
        await db.commit()
        job2, _, created2 = await ingest_discovery(db, greenhouse_offer(), method="reverse_ats")
        await db.commit()

        assert created1 is True
        assert created2 is False
        assert job1.id == job2.id
        # The strong source upgrades the canonical identity of the Job that
        # was only ever seen (so far) through a weak source.
        assert job2.source == "greenhouse"
        assert job2.canonical_url.endswith("/acme/jobs/456")

        discoveries = list(await db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == job1.id)))
        assert {d.source for d in discoveries} == {"linkedin", "greenhouse"}
        total_jobs = list(await db.scalars(select(Job)))
        assert len(total_jobs) == 1


async def test_ambiguous_match_never_merges(api):
    """Two genuinely different openings with the identical title at the same
    company must NOT be folded together just because company+title match."""
    _, sessions, _ = api
    async with sessions() as db:
        await ingest_discovery(db, greenhouse_offer(location="Madrid, Spain", posting_url="https://job-boards.greenhouse.io/acme/jobs/1"), method="reverse_ats")
        await ingest_discovery(db, greenhouse_offer(location="Berlin, Germany", posting_url="https://job-boards.greenhouse.io/acme/jobs/2", external_source_id="2"), method="reverse_ats")
        await db.commit()

        # A LinkedIn observation with no location can't disambiguate between
        # the two — it should NOT be merged onto either.
        job, _, created = await ingest_discovery(db, linkedin_offer(location=""), method="email_alert")
        await db.commit()

        assert created is True
        all_jobs = list(await db.scalars(select(Job)))
        assert len(all_jobs) == 3


async def test_different_title_same_company_does_not_merge(api):
    _, sessions, _ = api
    async with sessions() as db:
        await ingest_discovery(db, greenhouse_offer(title="Director of Engineering"), method="reverse_ats")
        await db.commit()
        job, _, created = await ingest_discovery(db, linkedin_offer(title="Engineering Manager"), method="email_alert")
        await db.commit()

        assert created is True
        all_jobs = list(await db.scalars(select(Job)))
        assert len(all_jobs) == 2


async def test_stale_posting_outside_match_window_does_not_merge(api):
    _, sessions, _ = api
    async with sessions() as db:
        old_posted = datetime.now(UTC) - timedelta(days=400)
        await ingest_discovery(db, greenhouse_offer(posted_at=old_posted), method="reverse_ats")
        await db.commit()
        job, _, created = await ingest_discovery(db, linkedin_offer(), method="email_alert")
        await db.commit()

        assert created is True
        all_jobs = list(await db.scalars(select(Job)))
        assert len(all_jobs) == 2


async def test_rescanning_same_source_updates_last_seen_without_duplicate_discovery(api):
    _, sessions, _ = api
    async with sessions() as db:
        job, discovery, _ = await ingest_discovery(db, greenhouse_offer(), method="reverse_ats")
        await db.commit()
        first_seen = discovery.first_seen_at

        job2, discovery2, created2 = await ingest_discovery(db, greenhouse_offer(), method="reverse_ats")
        await db.commit()

        assert created2 is False
        assert discovery2.id == discovery.id
        assert discovery2.first_seen_at == first_seen
        all_discoveries = list(await db.scalars(select(JobDiscovery)))
        assert len(all_discoveries) == 1


async def test_record_job_discovery_merges_metadata_on_rescan(api):
    _, sessions, _ = api
    async with sessions() as db:
        job = Job(canonical_key="k1", canonical_url="https://x/1", company="Acme", title="Director", posting_url="https://x/1", source="greenhouse")
        db.add(job)
        await db.flush()
        await record_job_discovery(db, job, source="greenhouse", method="reverse_ats", source_url="https://x/1", metadata={"a": 1})
        await db.commit()
        discovery = await record_job_discovery(db, job, source="greenhouse", method="reverse_ats", source_url="https://x/1", metadata={"b": 2})
        await db.commit()
        assert discovery.source_metadata == {"a": 1, "b": 2}


def test_normalize_title_is_conservative():
    assert normalize_title("Director of Engineering") == normalize_title("director   of engineering")
    assert normalize_title("Director, Engineering") != normalize_title("Director of Engineering")
    assert normalize_title("VP Engineering") != normalize_title("VP of Engineering")


async def test_weak_source_never_overwrites_strong_fields_even_on_exact_url_match(api):
    """If a weak-sourced payload somehow shares an exact canonical_url with an
    existing strong Job (e.g. a re-ingested identical row), its fields must
    still not clobber the canonical company/title/location."""
    _, sessions, _ = api
    async with sessions() as db:
        offer = greenhouse_offer(source="linkedin")
        job1, _, created1 = await ingest_discovery(db, offer, method="reverse_ats")
        await db.commit()
        assert created1 is True
        assert job1.source == "linkedin"

        same_url_weak = greenhouse_offer(source="linkedin", company="Different Co", title="Different Title")
        job2, _, created2 = await ingest_discovery(db, same_url_weak, method="email_alert")
        await db.commit()

        assert created2 is False
        assert job2.id == job1.id
        assert job2.company == "Acme Corp"
        assert job2.title == "Director of Engineering"
