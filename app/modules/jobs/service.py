import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.jobs.models import Job
from app.modules.jobs.schemas import JobIngest

TRACKING_PARAMS = {"fbclid", "gclid", "source", "ref", "referrer"}


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS))
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def canonical_job_key(company: str, title: str, canonical_url: str) -> str:
    value = "|".join((company.strip().casefold(), title.strip().casefold(), canonical_url))
    return hashlib.sha256(value.encode()).hexdigest()


async def upsert_job(db: AsyncSession, payload: JobIngest) -> tuple[Job, bool]:
    canonical_url = canonicalize_url(str(payload.posting_url))
    key = canonical_job_key(payload.company, payload.title, canonical_url)
    clauses = [Job.canonical_url == canonical_url, Job.canonical_key == key]
    if payload.external_source_id:
        clauses.append((Job.source == payload.source) & (Job.external_source_id == payload.external_source_id))
    job = await db.scalar(select(Job).where(or_(*clauses)))
    created = job is None
    if job is None:
        job = Job(canonical_key=key, canonical_url=canonical_url, company=payload.company, title=payload.title, posting_url=str(payload.posting_url))
        db.add(job)
    job.company = payload.company
    job.title = payload.title
    job.location = payload.location
    job.description = payload.description or job.description
    job.source = payload.source
    job.external_source_id = payload.external_source_id
    job.posting_url = str(payload.posting_url)
    job.direct_application_url = str(payload.direct_application_url) if payload.direct_application_url else job.direct_application_url
    job.posted_at = payload.posted_at or job.posted_at
    job.last_seen_at = utcnow()
    job.is_active = payload.is_active
    job.source_metadata = {**(job.source_metadata or {}), **payload.source_metadata}
    await db.flush()
    return job, created
