"""Candidate-scoped Discovery/Sources overview (Phase 5 Checkpoint E §2/§5).

No new metrics table (per instruction) — every count below is derived from
existing JobDiscovery + CandidateJob rows, scoped to the requesting
candidate's OWN CandidateJob rows so metrics never reflect another
candidate's funnel (§10). "Discovered" counts a CandidateJob once per
source/method even though the underlying Job may have several
JobDiscovery rows (one per channel that ever found it) — that's the point:
the same job counts toward every channel that surfaced it for THIS
candidate's pipeline.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.discovery.sources import (
    METHOD_COMPANY_WATCHLIST,
    METHOD_WEB_SEARCH,
    REVERSE_SCAN_SOURCES,
    SOURCE_CATALOG,
)
from app.modules.discovery.watchlist_service import list_watched_companies
from app.modules.integrations import service as integrations_service
from app.modules.jobs.models import Job, JobDiscovery
from app.modules.pipeline.models import CandidateJob

# The two feeds Checkpoint D's benchmark found worth keeping at low priority
# (Checkpoint E §9). Deprioritized feeds (Arbeitnow/Himalayas/Remotive/
# Jobicy) are intentionally NOT listed — they still run if enabled in a
# candidate's own portals.yml, but Munia's UI doesn't feature them by
# default per the strategic decision, and (see migration.service's
# import_pipeline docstring) scan.mjs doesn't persist enough per-row
# attribution to report clean per-feed metrics for them yet anyway.
FEATURED_JOB_FEEDS: tuple[tuple[str, str], ...] = (("wttj", "Welcome to the Jungle"), ("manfred", "getManfred"))

_EMPTY_METRICS = {"discovered": 0, "eligible": 0, "worth_evaluating": 0, "applied": 0}


@dataclass
class _Bucket:
    discovered: set = field(default_factory=set)
    eligible: set = field(default_factory=set)
    worth_evaluating: set = field(default_factory=set)
    applied: set = field(default_factory=set)

    def counts(self) -> dict[str, int]:
        return {"discovered": len(self.discovered), "eligible": len(self.eligible), "worth_evaluating": len(self.worth_evaluating), "applied": len(self.applied)}


async def _candidate_metric_buckets(db: AsyncSession, user_id: uuid.UUID) -> tuple[dict[str, _Bucket], dict[str, _Bucket]]:
    rows = (
        await db.execute(
            select(JobDiscovery.source, JobDiscovery.method, CandidateJob.id, CandidateJob.eligibility, CandidateJob.triage_result, CandidateJob.applied_at)
            .join(Job, Job.id == JobDiscovery.job_id)
            .join(CandidateJob, CandidateJob.job_id == Job.id)
            .where(CandidateJob.user_id == user_id)
        )
    ).all()

    by_source: dict[str, _Bucket] = defaultdict(_Bucket)
    by_method: dict[str, _Bucket] = defaultdict(_Bucket)
    for source, method, cj_id, eligibility, triage_result, applied_at in rows:
        for bucket in (by_source[source], by_method[method]):
            bucket.discovered.add(cj_id)
            if eligibility == "eligible":
                bucket.eligible.add(cj_id)
            if triage_result == "worth":
                bucket.worth_evaluating.add(cj_id)
            if applied_at is not None:
                bucket.applied.add(cj_id)
    return by_source, by_method


def _metrics_for(buckets: dict[str, _Bucket], key: str) -> dict[str, int]:
    bucket = buckets.get(key)
    return bucket.counts() if bucket else dict(_EMPTY_METRICS)


async def build_sources_overview(db: AsyncSession, user_id: uuid.UUID) -> dict:
    by_source, by_method = await _candidate_metric_buckets(db, user_id)

    integration = await integrations_service.get_integration(db, user_id, "gmail")
    linkedin_group = {
        "id": "linkedin",
        "label": "LinkedIn",
        "sources": [
            {
                "id": "linkedin",
                "label": "LinkedIn Job Alerts",
                "status": integration.status if integration else "disconnected",
                "last_sync_at": integration.last_sync_at if integration else None,
                "last_error": integration.last_error if integration else None,
                "metrics": _metrics_for(by_source, "linkedin"),
            }
        ],
    }

    network_group = {
        "id": "network_scan",
        "label": "Network Scans",
        "sources": [
            {"id": source_id, "label": SOURCE_CATALOG[source_id].label, "status": "active", "metrics": _metrics_for(by_source, source_id)}
            for source_id in sorted(REVERSE_SCAN_SOURCES)
        ],
    }

    watched = await list_watched_companies(db, user_id)
    watchlist_group = {
        "id": "company_watchlist",
        "label": "Company Watchlist",
        "summary": {
            "companies_watched": len(watched),
            "last_scan_at": max((w.last_scanned_at for w in watched if w.last_scanned_at), default=None),
            "errors": sum(1 for w in watched if w.scan_status == "error"),
        },
        "metrics": _metrics_for(by_method, METHOD_COMPANY_WATCHLIST),
        "companies": [
            {
                "id": w.id,
                "company_name": w.company_name,
                "careers_url": w.careers_url,
                "provider": w.provider,
                "enabled": w.enabled,
                "scan_status": w.scan_status,
                "last_scanned_at": w.last_scanned_at,
                "last_scan_error": w.last_scan_error,
            }
            for w in watched
        ],
    }

    # Job feeds: scan.mjs doesn't persist a per-row source label (see
    # migration.service.import_pipeline's docstring), so a clean per-feed
    # metric isn't available yet — shown as configured/featured only,
    # never with a fabricated count. Real per-source metrics ARE available
    # for direct-scan output once that gap closes.
    feed_group = {
        "id": "job_feed",
        "label": "Job Feeds",
        "sources": [{"id": feed_id, "label": label, "status": "active", "metrics_available": False} for feed_id, label in FEATURED_JOB_FEEDS],
    }

    web_group = {
        "id": "web_discovery",
        "label": "Web Discovery",
        "sources": [{"id": "web-discovery", "label": "Level-3 Web Search", "status": "active", "metrics": _metrics_for(by_method, METHOD_WEB_SEARCH)}],
    }

    return {"groups": [linkedin_group, network_group, watchlist_group, feed_group, web_group]}
