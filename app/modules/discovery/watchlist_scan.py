"""Company Watchlist scanning (Phase 5 Checkpoint D §2/§3/§4).

Reuses the vendored Career Ops engine's own provider layer (scan.mjs +
providers/*.mjs) exactly as-is — no provider parser is reimplemented here.
The only new code is: group watchers by distinct target (Checkpoint B's
distinct_scan_targets), materialize a throwaway ad-hoc portals.yml entry for
ONE target at a time in a shared (candidate-agnostic) workspace, run the
engine, and fold its output through jobs.service.ingest_discovery.

Why a shared workspace instead of one of the candidates' own: the target is
shared (Checkpoint D §3 — "scan that target ONCE"), so the scan must not run
inside any one candidate's identity/profile. `ensure_system_layer` (the same
helper `automation.workspace` uses for every per-candidate workspace) is
reused here, just pointed at a workspace nobody's CandidateProfile owns.

Provider detection order (Checkpoint D §4): a WatchedCompany's `provider` is
resolved once, at create/update time (discovery.sources.detect_provider off
the careers_url — see watchlist_service.py). Scanning here does NOT
re-derive or guess a provider from scratch: if a target has no known,
Career-Ops-supported provider, it's marked `unsupported_provider` and
skipped — never silently scanned as if it were a generic/guessed provider.
"""

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.automation.runner import run_in_workspace
from app.modules.automation.workspace import ensure_system_layer
from app.modules.candidates.relevance import relevant_to_candidate
from app.modules.candidates.service import get_profile
from app.modules.discovery.sources import METHOD_COMPANY_WATCHLIST, REVERSE_SCAN_SOURCES, WATCHLIST_ONLY_SOURCES
from app.modules.discovery.watchlist_service import ScanTarget, distinct_scan_targets, mark_scan_status
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.migration.parsers import pipeline_rows
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job

# Every provider Career Ops can actually resolve a watched company through —
# the union of the reverse-network sources (which also work fine pointed at
# one company) and the watchlist-only sources identified in Checkpoint A.
SUPPORTED_WATCHLIST_PROVIDERS: frozenset[str] = REVERSE_SCAN_SOURCES | WATCHLIST_ONLY_SOURCES

SCAN_TIMEOUT_SECONDS = 180
_EMPTY_PIPELINE = "# Pipeline — Pending URLs\n\n## Pending\n\n## Processed\n"


def shared_scan_workspace(settings: Settings) -> Path:
    """A single workspace, owned by no candidate, reused across every
    watchlist run and every target within it. `ensure_system_layer` links in
    the same providers/scan.mjs/lib the per-candidate workspaces use."""
    workspace = settings.career_ops_workspace_root.parent / "shared" / "watchlist"
    ensure_system_layer(workspace, settings)
    (workspace / "data").mkdir(parents=True, exist_ok=True)
    return workspace


def _write_target_portals_yaml(workspace: Path, target: ScanTarget) -> None:
    # No title_filter/location_filter: candidate relevance is applied AFTER
    # ingestion (Checkpoint D §9) — the shared scan must not pre-filter
    # postings using any one candidate's preferences.
    entry: dict[str, Any] = {"name": target.company_name, "careers_url": target.careers_url, "enabled": True}
    if target.provider:
        entry["provider"] = target.provider
    (workspace / "portals.yml").write_text(yaml.safe_dump({"tracked_companies": [entry]}, sort_keys=False), encoding="utf-8")


def _reset_scan_data(workspace: Path) -> None:
    # Reset before each target so scan.mjs's own dedup/history never masks a
    # posting from THIS run's parse — correctness comes from
    # ingest_discovery's unique constraint, not from this file surviving
    # between targets.
    (workspace / "data" / "pipeline.md").write_text(_EMPTY_PIPELINE, encoding="utf-8")
    (workspace / "data" / "scan-history.tsv").write_text("", encoding="utf-8")


async def scan_target(workspace: Path, settings: Settings, target: ScanTarget):
    _write_target_portals_yaml(workspace, target)
    _reset_scan_data(workspace)
    return await run_in_workspace(workspace, settings, "scan.mjs", "--json", timeout=SCAN_TIMEOUT_SECONDS)


async def run_watchlist_scan(db: AsyncSession, settings: Settings) -> dict[str, int]:
    targets = await distinct_scan_targets(db)
    workspace = shared_scan_workspace(settings)
    totals = {"targets": len(targets), "scanned_ok": 0, "unsupported_provider": 0, "failed": 0, "jobs_found": 0, "jobs_created": 0, "candidate_jobs_created": 0}
    profile_cache: dict = {}

    for target in targets:
        if not target.provider or target.provider not in SUPPORTED_WATCHLIST_PROVIDERS:
            totals["unsupported_provider"] += 1
            await mark_scan_status(db, target.watchlist_entry_ids, status="unsupported_provider", error="no known/supported ATS provider detected for this careers URL")
            continue

        # Per-target isolation: one company's provider/network failure must
        # never abort the rest of the watchlist run (Checkpoint D §8).
        try:
            result = await scan_target(workspace, settings, target)
            if result.returncode:
                raise RuntimeError((result.stderr or "scan.mjs failed")[-500:])
            rows = pipeline_rows((workspace / "data" / "pipeline.md").read_text(encoding="utf-8"))
        except Exception as error:
            totals["failed"] += 1
            await mark_scan_status(db, target.watchlist_entry_ids, status="error", error=str(error)[:500])
            continue

        jobs_this_target = []
        for row in rows:
            totals["jobs_found"] += 1
            payload = JobIngest(
                company=row.company,
                title=row.title,
                location=row.location,
                source=target.provider,
                posting_url=row.url,
                direct_application_url=row.url,
                source_metadata={"careers_url": target.careers_url or "", "watchlist_company": target.company_name},
            )
            job, _, created = await ingest_discovery(db, payload, method=METHOD_COMPANY_WATCHLIST)
            if created:
                totals["jobs_created"] += 1
            jobs_this_target.append(job)

        # Only THIS target's watchers get a CandidateJob — never every
        # candidate in the system (Checkpoint D §3/§9). Eligibility remains
        # each candidate's own profile-driven relevance check, unchanged.
        for user_id in target.watcher_user_ids:
            profile = profile_cache.get(user_id)
            if profile is None:
                profile = await get_profile(db, user_id)
                profile_cache[user_id] = profile
            for job in jobs_this_target:
                if not relevant_to_candidate(job, profile):
                    continue
                await add_candidate_job(db, user_id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Matched a watched company; awaiting cheap triage"))
                totals["candidate_jobs_created"] += 1

        totals["scanned_ok"] += 1
        await mark_scan_status(db, target.watchlist_entry_ids, status="ok", error=None)

    return totals
