"""Orchestrates one Gmail sync for one candidate's LinkedIn Job Alert
integration: decrypt token -> refresh -> list/get messages -> validate ->
parse -> app.modules.jobs.service.ingest_discovery -> CandidateJob.

This is the only place that ties together integrations (credentials),
discovery.gmail_client (transport), discovery.linkedin_alerts (parsing), and
jobs.service (dedup/canonical Job) for the LinkedIn email-alert path.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.discovery import gmail_client
from app.modules.discovery.linkedin_alerts import LINKEDIN_ALERT_SENDER, is_authentic_sender, parse_alert_message
from app.modules.integrations import gmail_oauth
from app.modules.integrations import service as integrations_service
from app.modules.integrations.models import CandidateIntegration
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job

METHOD_EMAIL_ALERT = "email_alert"
SOURCE_LINKEDIN = "linkedin"
DEFAULT_DAYS_BACK = 14
DEFAULT_MAX_RESULTS = 50


def _message_discovered_at(message: dict) -> datetime | None:
    internal_date = message.get("internalDate")
    if not internal_date:
        return None
    try:
        return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
    except (TypeError, ValueError):
        return None


async def sync_gmail_linkedin_alerts(db: AsyncSession, integration: CandidateIntegration, settings, *, http_client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    counts = {"messages_scanned": 0, "messages_skipped_untrusted": 0, "messages_skipped_malformed": 0, "jobs_found": 0, "jobs_created": 0, "jobs_attached": 0}
    already_processed = set((integration.sync_cursor or {}).get("processed_message_ids") or [])
    newly_processed: list[str] = []

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15)
    try:
        try:
            refresh_token = integrations_service.decrypt_refresh_token(settings, integration)
            access_token = await gmail_oauth.refresh_access_token(client_id=settings.google_oauth_client_id, client_secret=settings.google_oauth_client_secret, refresh_token=refresh_token, http_client=client)
        except Exception as error:
            # A refresh failure here means the credential itself is unusable
            # (revoked, malformed, key mismatch) — nothing below can proceed.
            await integrations_service.mark_sync_result(db, integration, ok=False, error=str(error)[:500])
            return {"status": "error", "error": str(error)[:500], **counts}

        try:
            messages = await gmail_client.list_messages(access_token=access_token, http_client=client, sender=LINKEDIN_ALERT_SENDER, days_back=DEFAULT_DAYS_BACK, max_results=DEFAULT_MAX_RESULTS)
        except Exception as error:
            await integrations_service.mark_sync_result(db, integration, ok=False, error=str(error)[:500])
            return {"status": "error", "error": str(error)[:500], **counts}

        for entry in messages:
            message_id = entry.get("id")
            if not message_id or message_id in already_processed:
                continue
            counts["messages_scanned"] += 1
            # Per-message isolation: one malformed/unexpected-shape email must
            # never abort the rest of the batch.
            try:
                message = await gmail_client.get_message(access_token=access_token, http_client=client, message_id=message_id)
                headers = (message.get("payload") or {}).get("headers") or []
                if not is_authentic_sender(headers):
                    counts["messages_skipped_untrusted"] += 1
                    newly_processed.append(message_id)
                    continue
                candidates = parse_alert_message(message)
                if not candidates:
                    counts["messages_skipped_malformed"] += 1
                    newly_processed.append(message_id)
                    continue
                discovered_at = _message_discovered_at(message)
                for candidate in candidates:
                    counts["jobs_found"] += 1
                    payload = JobIngest(
                        company=candidate.company,
                        title=candidate.title,
                        location=candidate.location,
                        source=SOURCE_LINKEDIN,
                        posting_url=candidate.url,
                        direct_application_url=candidate.url,
                        external_source_id=candidate.job_id,
                        source_metadata={"alert_sender": LINKEDIN_ALERT_SENDER},
                    )
                    job, _, created = await ingest_discovery(db, payload, method=METHOD_EMAIL_ALERT, user_id=integration.user_id, discovered_at=discovered_at)
                    if created:
                        counts["jobs_created"] += 1
                    await add_candidate_job(db, integration.user_id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added from LinkedIn Job Alert; awaiting cheap triage"))
                    counts["jobs_attached"] += 1
                newly_processed.append(message_id)
            except Exception:
                # Content/shape errors only — never logged with message body.
                counts["messages_skipped_malformed"] += 1
                continue

        await integrations_service.mark_sync_result(db, integration, ok=True, error=None, processed_message_ids=newly_processed)
        return {"status": "ok", "error": None, **counts}
    finally:
        if owns_client:
            await client.aclose()
