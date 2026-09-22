import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.discovery.sources import WEAK_SOURCES, is_weak_source
from app.modules.jobs.models import Job, JobDiscovery
from app.modules.jobs.schemas import JobIngest

TRACKING_PARAMS = {"fbclid", "gclid", "source", "ref", "referrer"}

# How far apart two observations' anchor dates (posted_at, falling back to
# first_seen_at) may be for the conservative cross-source match below to even
# consider them the same posting. Wide enough to absorb an ATS's own posting
# lag behind a LinkedIn alert, narrow enough that a same-titled role reopened
# months later isn't silently folded into the old one.
CONSERVATIVE_MATCH_WINDOW_DAYS = 45

_TITLE_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


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


def normalize_title(title: str) -> str:
    """Casefold + strip punctuation/whitespace for conservative title matching.

    Deliberately simple (no stemming/synonyms) — this is a dedup safety net,
    not a search relevance function. "Director, Engineering" and "Director of
    Engineering" are intentionally NOT equal here; being too eager to fold
    different titles together is exactly the "different openings, identical
    company" trap Phase 5 §10 warns against.
    """
    stripped = _TITLE_PUNCT_RE.sub(" ", title.casefold())
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def _as_aware(value: datetime) -> datetime:
    from datetime import UTC

    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _find_conservative_match(db: AsyncSession, *, company: str, title: str, location: str, reference_time: datetime, want_weak: bool) -> Job | None:
    """Find (at most) one existing Job that conservatively matches by
    company + normalized title + location + a time window, restricted to the
    opposite "strength" tier from the incoming observation.

    `want_weak=True` means the incoming observation is itself weak (e.g.
    linkedin) and may only attach to an existing STRONG-sourced Job (a
    Greenhouse/Lever/... posting found first). `want_weak=False` means the
    incoming observation is strong and may "upgrade" an existing WEAK-sourced
    Job (a LinkedIn-only Job found first, later confirmed on an ATS).

    Strong-to-strong and weak-to-weak are deliberately never matched here —
    two different ATSes rarely mirror the exact same posting under two URLs,
    and folding two independent weak observations together has no strong
    anchor to justify it. Ambiguity (more than one candidate) always loses:
    returns None rather than guessing, per Phase 5 §10.
    """
    company_key = company.strip().casefold()
    if not company_key:
        return None
    title_key = normalize_title(title)
    location_key = (location or "").strip().casefold()
    reference = _as_aware(reference_time)
    window_start = reference - timedelta(days=CONSERVATIVE_MATCH_WINDOW_DAYS)
    window_end = reference + timedelta(days=CONSERVATIVE_MATCH_WINDOW_DAYS)

    # want_weak=True (incoming is weak) must search the STRONG tier, and vice
    # versa — this is the "opposite strength tier" the docstring promises.
    weak_sources = list(WEAK_SOURCES)
    source_filter = Job.source.notin_(weak_sources) if want_weak else Job.source.in_(weak_sources)
    candidates = list(await db.scalars(select(Job).where(func.lower(Job.company) == company_key, source_filter)))

    matches: list[Job] = []
    for job in candidates:
        if normalize_title(job.title) != title_key:
            continue
        job_location_key = (job.location or "").strip().casefold()
        if location_key and job_location_key and location_key != job_location_key:
            continue
        anchor = job.posted_at or job.first_seen_at
        if anchor and not (window_start <= _as_aware(anchor) <= window_end):
            continue
        matches.append(job)
    return matches[0] if len(matches) == 1 else None


async def record_job_discovery(
    db: AsyncSession,
    job: Job,
    *,
    source: str,
    method: str,
    source_url: str,
    external_id: str | None = None,
    user_id: uuid.UUID | None = None,
    discovered_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> JobDiscovery:
    """Upsert a single observation of `job` through (source, method, source_url).

    Re-observing the same triple bumps `last_seen_at`/merges metadata instead
    of duplicating a row, so a daily rescan of the same watched company or
    the same LinkedIn alert doesn't pile up rows for one live posting.
    """
    canonical_source_url = canonicalize_url(source_url)
    discovery = await db.scalar(
        select(JobDiscovery).where(
            JobDiscovery.job_id == job.id,
            JobDiscovery.source == source,
            JobDiscovery.method == method,
            JobDiscovery.source_url == canonical_source_url,
        )
    )
    if discovery is None:
        discovery = JobDiscovery(
            job_id=job.id,
            user_id=user_id,
            source=source,
            method=method,
            source_url=canonical_source_url,
            external_id=external_id,
            discovered_at=discovered_at or utcnow(),
            source_metadata=metadata or {},
        )
        db.add(discovery)
    else:
        discovery.last_seen_at = utcnow()
        discovery.source_metadata = {**(discovery.source_metadata or {}), **(metadata or {})}
        if user_id is not None:
            discovery.user_id = user_id
        if external_id is not None:
            discovery.external_id = external_id
    await db.flush()
    return discovery


async def ingest_discovery(
    db: AsyncSession,
    payload: JobIngest,
    *,
    method: str,
    user_id: uuid.UUID | None = None,
    discovered_at: datetime | None = None,
) -> tuple[Job, JobDiscovery, bool]:
    """The dedup-aware entry point discovery paths should use instead of
    calling upsert_job directly: resolves `payload` onto a canonical Job
    (creating one only if nothing matches, strong or conservative) and always
    records a JobDiscovery observation.

    Matching, in order:
    1. Exact — same canonical_url/canonical_key, or same (source,
       external_source_id). Identical to upsert_job's own matching.
    2. Conservative cross-source — only when there's no exact match AND
       exactly one same-company/same-title/same-location/same-time-window
       Job exists on the "opposite strength" tier (see
       _find_conservative_match). Never triggered when ambiguous.

    A WEAK-sourced payload (see app.modules.discovery.sources.WEAK_SOURCES)
    NEVER overwrites an existing Job's canonical identity/fields — it only
    attaches an additional JobDiscovery. A STRONG-sourced payload may
    "upgrade" a Job that was only ever seen through a weak source.
    """
    canonical_url = canonicalize_url(str(payload.posting_url))
    key = canonical_job_key(payload.company, payload.title, canonical_url)
    weak = is_weak_source(payload.source)

    clauses = [Job.canonical_url == canonical_url, Job.canonical_key == key]
    if payload.external_source_id:
        clauses.append((Job.source == payload.source) & (Job.external_source_id == payload.external_source_id))
    job = await db.scalar(select(Job).where(or_(*clauses)))
    created = False

    if job is None:
        job = await _find_conservative_match(db, company=payload.company, title=payload.title, location=payload.location, reference_time=discovered_at or utcnow(), want_weak=weak)

    if job is None:
        job = Job(canonical_key=key, canonical_url=canonical_url, company=payload.company, title=payload.title, location=payload.location, description=payload.description, source=payload.source, external_source_id=payload.external_source_id, posting_url=str(payload.posting_url), direct_application_url=str(payload.direct_application_url) if payload.direct_application_url else None, posted_at=payload.posted_at, is_active=payload.is_active, source_metadata=dict(payload.source_metadata))
        db.add(job)
        created = True
        await db.flush()
    elif not weak:
        # A strong observation always refreshes the canonical fields — either
        # this IS the canonical strong source rescanning itself (a no-op on
        # canonical_url/key), or it's upgrading a Job that only had a weak
        # (e.g. linkedin) identity so far.
        job.company = payload.company
        job.title = payload.title
        job.location = payload.location or job.location
        job.description = payload.description or job.description
        job.source = payload.source
        job.external_source_id = payload.external_source_id
        job.canonical_url = canonical_url
        job.canonical_key = key
        job.posting_url = str(payload.posting_url)
        job.direct_application_url = str(payload.direct_application_url) if payload.direct_application_url else job.direct_application_url
        job.posted_at = payload.posted_at or job.posted_at
        job.is_active = payload.is_active
        job.last_seen_at = utcnow()
        job.source_metadata = {**(job.source_metadata or {}), **payload.source_metadata}
        await db.flush()
    else:
        # Weak observation attaching to an already-known (strong-sourced) Job:
        # bump last_seen_at only, never touch the canonical identity/fields.
        job.last_seen_at = utcnow()
        await db.flush()

    discovery = await record_job_discovery(db, job, source=payload.source, method=method, source_url=str(payload.posting_url), external_id=payload.external_source_id, user_id=user_id, discovered_at=discovered_at, metadata=dict(payload.source_metadata))
    return job, discovery, created
