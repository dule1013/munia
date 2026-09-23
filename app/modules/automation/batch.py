import asyncio
import hashlib
import json
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.automation.runner import CommandResult, run_for_candidate
from app.modules.automation.workspace import candidate_environment, materialize_profile
from app.modules.candidates.models import CandidateProfile, User
from app.modules.candidates.relevance import relevant_to_candidate
from app.modules.candidates.service import get_profile
from app.modules.discovery.ats_rotation import DEFAULT_BATCH_SIZES, advance_cursor, get_or_create_cursor, next_batch
from app.modules.discovery.linkedin_ingest import sync_gmail_linkedin_alerts
from app.modules.discovery.sources import METHOD_DIRECT_SCAN, METHOD_REVERSE_ATS, METHOD_WEB_SEARCH
from app.modules.discovery.watchlist_scan import run_watchlist_scan
from app.modules.integrations.models import CandidateIntegration
from app.modules.jobs.models import Job
from app.modules.migration.parsers import pipeline_rows, shortlist_rows
from app.modules.migration.service import import_pipeline
from app.modules.pipeline.models import CandidateJob


async def populate_candidate_jobs(db: AsyncSession) -> int:
    users = (await db.execute(select(User, CandidateProfile).join(CandidateProfile))).all()
    jobs = list(await db.scalars(select(Job).where(Job.is_active.is_(True))))
    created = 0
    for user, profile in users:
        existing = set(await db.scalars(select(CandidateJob.job_id).where(CandidateJob.user_id == user.id)))
        for job in jobs:
            if job.id in existing or not relevant_to_candidate(job, profile):
                continue
            db.add(CandidateJob(user_id=user.id, job_id=job.id, triage_result="uncertain", triage_reason="Matched candidate search preferences; awaiting automated triage", pipeline_status="Inbox"))
            created += 1
    await db.commit()
    return created


async def direct_discovery(db: AsyncSession, settings: Settings) -> dict[str, int]:
    profiles = (await db.execute(select(User, CandidateProfile).join(CandidateProfile))).all()
    groups: dict[str, list[User]] = defaultdict(list)
    for user, profile in profiles:
        groups[hashlib.sha256(profile.portals_yaml.encode()).hexdigest()].append(user)
    discovered = 0
    for users in groups.values():
        representative = users[0]
        result = await run_for_candidate(db, representative.id, settings, "scan.mjs", "--since", "7", "--verify", timeout=900)
        if result.returncode:
            continue
        workspace = settings.career_ops_workspace_root / str(representative.id)
        before = len(list(await db.scalars(select(Job.id))))
        await import_pipeline(db, representative, workspace, method=METHOD_DIRECT_SCAN)
        after = len(list(await db.scalars(select(Job.id))))
        discovered += max(0, after - before)
    matched = await populate_candidate_jobs(db)
    return {"discovered": discovered, "candidate_jobs": matched, "unique_search_configs": len(groups)}


async def reverse_discovery(db: AsyncSession, settings: Settings, ats: str, limit: int) -> dict[str, int]:
    profiles = (await db.execute(select(User, CandidateProfile).join(CandidateProfile))).all()
    groups: dict[str, User] = {}
    for user, profile in profiles:
        groups.setdefault(hashlib.sha256(profile.portals_yaml.encode()).hexdigest(), user)
    discovered = 0
    for representative in groups.values():
        result = await run_for_candidate(db, representative.id, settings, "scan-ats-full.mjs", "--since", "7", "--ats", ats, "--limit", str(limit), "--shuffle", "--liveness", timeout=1800)
        if result.returncode:
            continue
        workspace = settings.career_ops_workspace_root / str(representative.id)
        before = len(list(await db.scalars(select(Job.id))))
        await import_pipeline(db, representative, workspace, method=METHOD_REVERSE_ATS, default_source=ats)
        after = len(list(await db.scalars(select(Job.id))))
        discovered += max(0, after - before)
    return {"discovered": discovered, "candidate_jobs": await populate_candidate_jobs(db), "unique_search_configs": len(groups)}


async def rotating_reverse_discovery(db: AsyncSession, settings: Settings, ats: str, batch_size: int | None = None) -> dict:
    """The deterministic-rotation counterpart to reverse_discovery (Phase 5
    follow-up §C), for AUTOMATED morning discovery — manual Explore Scan and
    the standalone `run_multi_user_automation.py <ats>` mode are unaffected
    and keep using reverse_discovery's --shuffle behavior.

    Reuses one --json --dry-run-free scan-ats-full.mjs invocation per call
    (same as reverse_discovery) but with --offset from a persistent
    AtsScanCursor instead of --shuffle, and only advances that cursor when
    the scan actually SUCCEEDS — a failed/partial run leaves next_offset
    where it was so no slice of the network is silently skipped.
    """
    batch_size = batch_size or DEFAULT_BATCH_SIZES.get(ats, 200)
    cursor = await get_or_create_cursor(db, ats)
    offset, limit = next_batch(cursor, batch_size)
    await db.commit()

    profiles = (await db.execute(select(User, CandidateProfile).join(CandidateProfile))).all()
    groups: dict[str, User] = {}
    for user, profile in profiles:
        groups.setdefault(hashlib.sha256(profile.portals_yaml.encode()).hexdigest(), user)

    discovered = 0
    dataset_size = cursor.dataset_size or 0
    overall_status = "ok"
    last_error: str | None = None
    for representative in groups.values():
        result = await run_for_candidate(db, representative.id, settings, "scan-ats-full.mjs", "--since", "7", "--ats", ats, "--limit", str(limit), "--offset", str(offset), "--json", "--liveness", timeout=1800)
        if result.returncode:
            overall_status = "error"
            last_error = (result.stderr or "")[-2000:] or "scan failed"
            continue
        try:
            payload = json.loads(result.stdout)
            dataset_size = payload.get("datasetSize", {}).get(ats) or dataset_size
        except (json.JSONDecodeError, ValueError):
            pass
        workspace = settings.career_ops_workspace_root / str(representative.id)
        before = len(list(await db.scalars(select(Job.id))))
        await import_pipeline(db, representative, workspace, method=METHOD_REVERSE_ATS, default_source=ats)
        after = len(list(await db.scalars(select(Job.id))))
        discovered += max(0, after - before)

    cursor = await get_or_create_cursor(db, ats)  # re-fetch: prior commits may have expired it
    await advance_cursor(db, cursor, scanned_offset=offset, batch_size=limit, dataset_size=dataset_size, status=overall_status, error=last_error)
    await db.commit()

    return {"source": ats, "offset": offset, "batch_size": limit, "dataset_size": dataset_size, "next_offset": cursor.next_offset, "status": overall_status, "discovered": discovered, "candidate_jobs": await populate_candidate_jobs(db), "unique_search_configs": len(groups)}


async def watchlist_all(db: AsyncSession, settings: Settings) -> dict[str, int]:
    """Thin wrapper so scripts/run_multi_user_automation.py has one call site
    per mode, matching direct_discovery/reverse_discovery/level3_all. The
    actual scan-once-per-shared-target logic lives in discovery.watchlist_scan
    (Checkpoint D), which already isolates per-target failures internally."""
    return await run_watchlist_scan(db, settings)


async def linkedin_alert_sync_all(db: AsyncSession, settings: Settings) -> dict[str, int]:
    """Runs a Gmail/LinkedIn Job Alert sync for every candidate with a usable
    Gmail connection. Candidates are processed sequentially and in complete
    isolation: one candidate's Gmail/network failure is caught, recorded on
    THEIR integration (visible via GET /integrations/gmail/status), and never
    aborts the run for anyone else. No email content or token material is
    logged — only aggregate counts and, on failure, the short provider-side
    error string already sanitized by sync_gmail_linkedin_alerts.
    """
    integrations = list(await db.scalars(select(CandidateIntegration).where(CandidateIntegration.provider == "gmail", CandidateIntegration.status.in_(("connected", "error", "revoked")), CandidateIntegration.encrypted_credentials.is_not(None))))
    totals = {"candidates": len(integrations), "candidates_ok": 0, "candidates_failed": 0, "jobs_found": 0, "jobs_created": 0, "jobs_attached": 0}
    for integration in integrations:
        try:
            result = await sync_gmail_linkedin_alerts(db, integration, settings)
        except Exception:
            totals["candidates_failed"] += 1
            continue
        if result.get("status") == "ok":
            totals["candidates_ok"] += 1
        else:
            totals["candidates_failed"] += 1
        totals["jobs_found"] += result.get("jobs_found", 0)
        totals["jobs_created"] += result.get("jobs_created", 0)
        totals["jobs_attached"] += result.get("jobs_attached", 0)
    return totals


def triage_prompt() -> str:
    return """Run the Career Ops cheap morning triage for this candidate only. Read modes/_brief.md, config/profile.yml, modes/_profile.md, data/pipeline.md, and modes/pipeline.md. For every pending URL, fetch the JD through node fetch-jd.mjs first and use the documented fallback when needed. Run node check-liveness.mjs for every Level-3 or uncertain URL before retaining it. Mark obvious hard discards processed. Preserve genuine uncertainty. Write data/shortlist.md with only Worth evaluating and Uncertain sections and include URL, company, title, location, source, eligibility, and concise reason. Never evaluate, generate a CV, apply, or contact anyone."""


async def persist_triage_results(db: AsyncSession, user_id: uuid.UUID, workspace) -> int:
    shortlist, recognized = shortlist_rows((workspace / "data" / "shortlist.md").read_text(encoding="utf-8"))
    if not recognized:
        raise ValueError("shortlist has no canonical triage sections")
    pipeline = {row.url: row for row in pipeline_rows((workspace / "data" / "pipeline.md").read_text(encoding="utf-8"))}
    items = (await db.execute(select(CandidateJob, Job).join(Job).where(CandidateJob.user_id == user_id, CandidateJob.pipeline_status == "Inbox"))).all()
    changed = 0
    try:
        for item, job in items:
            outcome = shortlist.get(job.posting_url) or shortlist.get(job.canonical_url)
            row = pipeline.get(job.posting_url) or pipeline.get(job.canonical_url)
            if outcome:
                item.eligibility = outcome.eligibility
                item.triage_result = outcome.bucket
                item.triage_reason = outcome.reason
                item.triage_metadata = {"source": outcome.source or job.source, "location": outcome.location or job.location, "posted": outcome.posted, "shortlist_company": outcome.company, "shortlist_title": outcome.title}
                item.skipped = False
                changed += 1
            elif row and row.done:
                item.eligibility = row.labels.get("eligibility") or "ineligible"
                item.triage_result = "discard"
                item.triage_reason = row.labels.get("reason") or row.labels.get("note") or "Discarded by automated triage"
                item.triage_metadata = {"source": row.labels.get("source") or job.source, "location": row.location or job.location, "posted": row.labels.get("posted", ""), "liveness": row.labels.get("liveness", "")}
                item.pipeline_status = "Discarded"
                item.skipped = True
                changed += 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return changed


async def triage_all(db: AsyncSession, settings: Settings) -> dict[str, int]:
    users = list(await db.scalars(select(User).order_by(User.created_at)))
    processed = 0
    for user in users:
        result = await _run_agent(db, user.id, settings, triage_prompt(), "claude-haiku-4-5")
        if result.returncode:
            continue
        workspace = settings.career_ops_workspace_root / str(user.id)
        try:
            processed += await persist_triage_results(db, user.id, workspace)
        except (OSError, ValueError):
            await db.rollback()
    return {"users": len(users), "processed": processed}


async def level3_all(db: AsyncSession, settings: Settings) -> dict[str, int]:
    users = list(await db.scalars(select(User).order_by(User.created_at)))
    completed = 0
    prompt = "Read portals.yml search_queries and run Career Ops Level-3 discovery for this candidate. Verify every result with node check-liveness.mjs before adding it to data/pipeline.md. Add only active jobs matching title and location filters. Never evaluate, generate a CV, apply, or contact anyone."
    for user in users:
        result = await _run_agent(db, user.id, settings, prompt, "claude-haiku-4-5")
        if result.returncode:
            continue
        await import_pipeline(db, user, settings.career_ops_workspace_root / str(user.id), method=METHOD_WEB_SEARCH)
        completed += 1
    await populate_candidate_jobs(db)
    return {"users": len(users), "completed": completed}


async def _run_agent(db: AsyncSession, user_id: uuid.UUID, settings: Settings, prompt: str, model: str):
    profile = await get_profile(db, user_id)
    workspace = await asyncio.to_thread(materialize_profile, user_id, profile, settings)
    process = await asyncio.create_subprocess_exec("claude", "-p", prompt, "--model", model, "--permission-mode", "acceptEdits", "--allowedTools", "Read,WebFetch,WebSearch,Write,Edit,Bash,Glob,Grep", "--disallowedTools", "MultiEdit,NotebookEdit,Task", cwd=workspace, env=candidate_environment(workspace), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=1200)
    return CommandResult(process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace"))
