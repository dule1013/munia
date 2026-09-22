import base64
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.crypto import generate_key
from app.modules.candidates.models import User
from app.modules.discovery import gmail_client
from app.modules.discovery.linkedin_alerts import LINKEDIN_ALERT_SENDER
from app.modules.discovery.linkedin_ingest import sync_gmail_linkedin_alerts
from app.modules.integrations import gmail_oauth, service
from app.modules.jobs.models import Job, JobDiscovery
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.models import CandidateJob


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def gmail_message(msg_id: str, *, subject: str, body: str, from_header: str = f"LinkedIn Job Alerts <{LINKEDIN_ALERT_SENDER}>", dmarc: str = "dmarc=pass") -> dict:
    headers = [{"name": "Subject", "value": subject}, {"name": "From", "value": from_header}]
    if dmarc:
        headers.append({"name": "Authentication-Results", "value": f"mx.google.com; spf=pass; {dmarc}; dkim=pass"})
    internal_date = str(int(datetime.now(UTC).timestamp() * 1000))
    return {"id": msg_id, "internalDate": internal_date, "payload": {"headers": headers, "body": {"data": b64(body)}}}


ACME_ALERT = gmail_message("m1", subject="Acme Corp is hiring a Director of Engineering", body='<a href="https://www.linkedin.com/jobs/view/4001112222?trk=email">Apply</a>')


async def seed_user(sessions, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.commit()
        return user


async def make_integration(sessions, settings, user):
    async with sessions() as db:
        return await service.store_tokens(db, settings, user_id=user.id, provider="gmail", refresh_token="rt-1", account_email="candidate@gmail.com", scopes=gmail_oauth.GMAIL_READONLY_SCOPE)


def patch_gmail(monkeypatch, *, messages, get_message_by_id):
    async def fake_refresh(**kwargs):
        return "access-token-1"

    async def fake_list(**kwargs):
        return messages

    async def fake_get(*, access_token, http_client, message_id):
        return get_message_by_id[message_id]

    monkeypatch.setattr(gmail_oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(gmail_client, "list_messages", fake_list)
    monkeypatch.setattr(gmail_client, "get_message", fake_get)


def configure(settings):
    settings.google_oauth_client_id = "id"
    settings.google_oauth_client_secret = "secret"
    settings.google_oauth_redirect_uri = "https://api.example.com/cb"
    settings.integration_encryption_key = generate_key()


async def test_linkedin_alert_creates_job_discovery_and_candidate_job(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    integration = await make_integration(sessions, settings, user)
    patch_gmail(monkeypatch, messages=[{"id": "m1"}], get_message_by_id={"m1": ACME_ALERT})

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        result = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert result["status"] == "ok"
        assert result["jobs_created"] == 1
        assert result["jobs_attached"] == 1

        job = await db.scalar(select(Job))
        assert job.source == "linkedin"
        assert job.canonical_url == "https://www.linkedin.com/jobs/view/4001112222"

        discovery = await db.scalar(select(JobDiscovery).where(JobDiscovery.job_id == job.id))
        assert discovery.source == "linkedin"
        assert discovery.method == "email_alert"
        assert discovery.user_id == user.id

        candidate_job = await db.scalar(select(CandidateJob).where(CandidateJob.job_id == job.id))
        assert candidate_job is not None
        assert candidate_job.user_id == user.id


async def test_duplicate_gmail_message_is_not_reprocessed(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    await make_integration(sessions, settings, user)
    patch_gmail(monkeypatch, messages=[{"id": "m1"}], get_message_by_id={"m1": ACME_ALERT})

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        first = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert first["messages_scanned"] == 1

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        second = await sync_gmail_linkedin_alerts(db, integration, settings)
        # Already-seen message id is skipped before it's even fetched again.
        assert second["messages_scanned"] == 0
        assert second["jobs_found"] == 0

        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1


async def test_same_linkedin_job_from_two_different_messages_is_one_job(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    await make_integration(sessions, settings, user)
    second_alert = gmail_message("m2", subject="Acme Corp is hiring a Director of Engineering", body='https://www.linkedin.com/comm/jobs/view/4001112222?trk=digest')
    patch_gmail(monkeypatch, messages=[{"id": "m1"}, {"id": "m2"}], get_message_by_id={"m1": ACME_ALERT, "m2": second_alert})

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        result = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert result["jobs_found"] == 2
        assert result["jobs_created"] == 1  # second observation attaches, doesn't create

        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1
        discoveries = list(await db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == jobs[0].id)))
        assert len(discoveries) == 1  # same (job, source, method, source_url) triple re-observed, not duplicated


async def test_linkedin_job_already_existing_from_greenhouse_attaches_discovery(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    await make_integration(sessions, settings, user)
    patch_gmail(monkeypatch, messages=[{"id": "m1"}], get_message_by_id={"m1": ACME_ALERT})

    async with sessions() as db:
        greenhouse_payload = JobIngest(company="Acme Corp", title="Director of Engineering", location="", source="greenhouse", posting_url="https://job-boards.greenhouse.io/acme/jobs/999", direct_application_url="https://job-boards.greenhouse.io/acme/jobs/999", external_source_id="999")
        existing_job, _, _ = await ingest_discovery(db, greenhouse_payload, method="reverse_ats")
        await db.commit()
        existing_job_id = existing_job.id

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        result = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert result["jobs_created"] == 0  # attached to the existing Greenhouse job, not a new one

        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1
        assert jobs[0].id == existing_job_id
        assert jobs[0].source == "greenhouse"  # strong source untouched by the weak LinkedIn observation

        discoveries = list(await db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == existing_job_id)))
        assert {d.source for d in discoveries} == {"greenhouse", "linkedin"}


async def test_greenhouse_arriving_after_linkedin_upgrades_the_job(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    await make_integration(sessions, settings, user)
    patch_gmail(monkeypatch, messages=[{"id": "m1"}], get_message_by_id={"m1": ACME_ALERT})

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        await sync_gmail_linkedin_alerts(db, integration, settings)

    async with sessions() as db:
        greenhouse_payload = JobIngest(company="Acme Corp", title="Director of Engineering", location="", source="greenhouse", posting_url="https://job-boards.greenhouse.io/acme/jobs/999", direct_application_url="https://job-boards.greenhouse.io/acme/jobs/999", external_source_id="999")
        job, _, created = await ingest_discovery(db, greenhouse_payload, method="reverse_ats")
        await db.commit()
        assert created is False
        assert job.source == "greenhouse"

        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1


async def test_one_bad_email_does_not_abort_the_batch(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    await make_integration(sessions, settings, user)
    malformed = {"id": "bad", "internalDate": "1758540000000", "payload": {"headers": [{"name": "Subject", "value": "Acme Corp is hiring a Director of Engineering"}, {"name": "From", "value": f"LinkedIn <{LINKEDIN_ALERT_SENDER}>"}, {"name": "Authentication-Results", "value": "dmarc=pass"}], "body": {"data": "%%% not valid base64 at all %%%"}}}
    patch_gmail(monkeypatch, messages=[{"id": "bad"}, {"id": "m1"}], get_message_by_id={"bad": malformed, "m1": ACME_ALERT})

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        result = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert result["status"] == "ok"
        assert result["messages_scanned"] == 2
        assert result["jobs_created"] == 1  # the good message still went through

        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1


async def test_spoofed_sender_is_skipped_and_not_ingested(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    await make_integration(sessions, settings, user)
    spoofed = gmail_message("m1", subject="Acme Corp is hiring a Director of Engineering", body='https://www.linkedin.com/jobs/view/4001112222', from_header="LinkedIn <jobalerts-noreply@linked1n-fake.com>")
    patch_gmail(monkeypatch, messages=[{"id": "m1"}], get_message_by_id={"m1": spoofed})

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        result = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert result["messages_skipped_untrusted"] == 1
        assert result["jobs_found"] == 0

        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 0


async def test_malformed_alert_with_no_url_is_skipped(api, monkeypatch):
    _, sessions, settings = api
    configure(settings)
    user = await seed_user(sessions)
    await make_integration(sessions, settings, user)
    no_url = gmail_message("m1", subject="Acme Corp is hiring a Director of Engineering", body="no links in this alert at all")
    patch_gmail(monkeypatch, messages=[{"id": "m1"}], get_message_by_id={"m1": no_url})

    async with sessions() as db:
        integration = await service.get_integration(db, user.id, "gmail")
        result = await sync_gmail_linkedin_alerts(db, integration, settings)
        assert result["messages_skipped_malformed"] == 1
        assert result["jobs_found"] == 0
