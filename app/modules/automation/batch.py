import asyncio
import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.ai_config import service as ai_config_service
from app.modules.automation.runner import CommandResult, run_for_candidate
from app.modules.automation.workspace import candidate_environment, materialize_profile
from app.modules.candidates.models import CandidateProfile, User
from app.modules.candidates.relevance import relevant_to_candidate
from app.modules.candidates.service import get_profile
from app.modules.discovery.ai_search import AISearchNotConfigured, AISearchRateLimited, build_daily_discovery_query, run_ai_search
from app.modules.discovery.ats_rotation import DEFAULT_BATCH_SIZES, advance_cursor, get_or_create_cursor, next_batch
from app.modules.discovery.linkedin_ingest import sync_gmail_linkedin_alerts
from app.modules.discovery.models import MorningRun
from app.modules.discovery.sources import METHOD_DIRECT_SCAN, METHOD_REVERSE_ATS, METHOD_WEB_SEARCH, REVERSE_SCAN_SOURCES
from app.modules.discovery.watchlist_scan import run_watchlist_scan
from app.modules.integrations.models import CandidateIntegration
from app.modules.jobs.models import Job
from app.modules.migration.parsers import pipeline_rows, shortlist_rows
from app.modules.migration.service import import_pipeline
from app.modules.pipeline.fit_assessment import NoAIConfigured, apply_assessment, assess_fit
from app.modules.pipeline.hosted_triage import triage_candidate_hosted
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.service import INBOX_TRIAGE_RESULTS, apply_location_eligibility, has_candidate_decision


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
            # Skip a job the candidate already resolved themselves, AND a
            # job that was ALREADY really triaged before (triaged_at set) —
            # the latter is what stops a rediscovered-from-another-source
            # job from being silently re-triaged (and potentially reset)
            # every morning; has_candidate_decision alone doesn't catch this
            # since a real triage_result of "worth"/"uncertain" doesn't
            # itself count as a human decision.
            if has_candidate_decision(item) or item.triaged_at is not None:
                continue
            outcome = shortlist.get(job.posting_url) or shortlist.get(job.canonical_url)
            row = pipeline.get(job.posting_url) or pipeline.get(job.canonical_url)
            if outcome:
                item.eligibility = outcome.eligibility
                item.triage_result = outcome.bucket
                item.triage_reason = outcome.reason
                item.triage_metadata = {"source": outcome.source or job.source, "location": outcome.location or job.location, "posted": outcome.posted, "shortlist_company": outcome.company, "shortlist_title": outcome.title}
                item.skipped = False
                item.triaged_at = datetime.now(timezone.utc)
                changed += 1
            elif row and row.done:
                item.eligibility = row.labels.get("eligibility") or "ineligible"
                item.triage_result = "discard"
                item.triage_reason = row.labels.get("reason") or row.labels.get("note") or "Discarded by automated triage"
                item.triage_metadata = {"source": row.labels.get("source") or job.source, "location": row.location or job.location, "posted": row.labels.get("posted", ""), "liveness": row.labels.get("liveness", "")}
                item.pipeline_status = "Discarded"
                item.skipped = True
                item.triaged_at = datetime.now(timezone.utc)
                changed += 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return changed


async def _triage_one_candidate(db: AsyncSession, settings: Settings, user_id: uuid.UUID) -> dict:
    """Extracted from triage_all's loop body so the morning orchestrator can
    run cheap triage for ONE candidate as part of its own per-candidate
    cycle (Phase 5 follow-up correction), while triage_all keeps working
    unchanged for the standalone `run_multi_user_automation.py triage` mode.
    Never raises — a agent/CLI failure (e.g. the `claude` binary not being
    available on this deployment) is reported as a status string so the
    morning run summary can distinguish "triage genuinely found nothing new"
    from "triage couldn't run at all"."""
    try:
        result = await _run_agent(db, user_id, settings, triage_prompt(), "claude-haiku-4-5")
    except Exception as error:
        return {"status": "error", "error": f"triage agent could not start: {error}"[:500]}
    if result.returncode:
        return {"status": "error", "error": (result.stderr or "")[-500:] or "triage agent exited non-zero"}
    workspace = settings.career_ops_workspace_root / str(user_id)
    try:
        processed = await persist_triage_results(db, user_id, workspace)
    except (OSError, ValueError) as error:
        await db.rollback()
        return {"status": "error", "error": str(error)[:500]}
    return {"status": "ok", "processed": processed}


async def triage_all(db: AsyncSession, settings: Settings) -> dict[str, int]:
    users = list(await db.scalars(select(User).order_by(User.created_at)))
    processed = 0
    for user in users:
        outcome = await _triage_one_candidate(db, settings, user.id)
        if outcome["status"] == "ok":
            processed += outcome["processed"]
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


async def _candidate_morning_cycle(db: AsyncSession, settings: Settings, user: User, run_id: uuid.UUID) -> dict:
    """Per-candidate steps 4/6/8 of the morning cycle (Phase 5 follow-up
    §E/§6): AI/web discovery, location eligibility, lightweight fit
    assessment — everything candidate-specific, as opposed to the shared
    reverse-ATS/watchlist work already done once globally before this runs.
    A candidate with no AI configured (or an invalid/exhausted key) simply
    skips the AI-dependent steps with a clear status; it never raises past
    this function, so one candidate's AI trouble can't affect another's."""
    result: dict = {"ai_discovery": None, "location_classified": 0, "triage": None, "fit_assessed": 0}

    ai_config = await ai_config_service.get_ai_config(db, user.id)
    if ai_config is None:
        result["ai_status"] = "skipped_not_configured"
    else:
        try:
            profile = await get_profile(db, user.id)
            query = build_daily_discovery_query(profile.profile if profile else {})
            search_result = await run_ai_search(db, settings, user, query)
            result["ai_discovery"] = search_result
            result["ai_status"] = "ok" if search_result.get("status") == "ok" else "error"
        except AISearchNotConfigured:
            result["ai_status"] = "skipped_not_configured"
        except AISearchRateLimited:
            result["ai_status"] = "skipped_rate_limited"
        except Exception as error:
            result["ai_status"] = "error"
            result["ai_error"] = str(error)[:500]

    # Location eligibility — deterministic, runs regardless of AI config.
    # ineligible jobs are hard-discarded (triage_result="discard") right
    # here, so cheap triage below never even sees them.
    try:
        result["location_classified"] = await apply_location_eligibility(db, user.id)
    except Exception as error:
        result["location_error"] = str(error)[:500]

    # Cheap candidate-specific triage — hosted architecture (Phase 5 follow-
    # up correction): this candidate's own Anthropic key, NOT the CLI-agent
    # path (automation.batch.triage_all/_run_agent, which needs the `claude`
    # binary — deliberately not installed in Dockerfile.api). No AI
    # configured -> "skipped_not_configured", not an error; the run still
    # completes normally. Reported separately in the summary so a triage
    # failure is diagnosable on its own, distinct from an AI-discovery/
    # assessment failure. triage_candidate_hosted itself skips anything
    # already triaged (triaged_at set), location-ineligible, or human-decided.
    triage_outcome = await triage_candidate_hosted(db, settings, user.id)
    result["triage"] = triage_outcome

    # Lightweight fit assessment — only for jobs that (a) actually went
    # through REAL triage (triaged_at set — never the fresh "uncertain"
    # placeholder, which triage_result alone can't distinguish), (b)
    # survived it ("worth", or genuinely "uncertain" — triage's own
    # ambiguity is exactly what the deeper assessment exists to resolve),
    # (c) aren't location-ineligible, and (d) haven't been assessed yet —
    # this last check is also what stops a rediscovered-from-another-source
    # already-"strong" job from being reassessed for no reason. Only runs
    # when AI is configured.
    if ai_config is not None:
        rows = await db.execute(
            select(CandidateJob, Job)
            .join(Job, Job.id == CandidateJob.job_id)
            .where(
                CandidateJob.user_id == user.id,
                CandidateJob.pipeline_status == "Inbox",
                CandidateJob.skipped.is_(False),
                CandidateJob.triaged_at.is_not(None),
                CandidateJob.triage_result.in_(INBOX_TRIAGE_RESULTS),
                or_(CandidateJob.eligibility.is_(None), CandidateJob.eligibility != "ineligible"),
                CandidateJob.ai_fit.is_(None),
            )
        )
        assessed = 0
        for item, job in rows.all():
            try:
                assessment = await assess_fit(db, settings, item, job)
            except NoAIConfigured:
                break  # key was removed mid-loop; stop this candidate's assessments, not the run
            except Exception:
                continue  # one bad job assessment must not stop the rest of this candidate's queue
            if assessment:
                await apply_assessment(db, item, assessment, run_id=run_id)
                assessed += 1
        await db.commit()
        result["fit_assessed"] = assessed

    return result


async def morning_run(db: AsyncSession, settings: Settings) -> dict:
    """The single top-level automation Railway schedules (Phase 5 follow-up
    §5): LinkedIn -> Watchlist -> rotating ATS slices (shared/global work,
    done once) -> per-candidate AI discovery/location/fit-assessment
    (candidate-specific) -> Today qualification is implicit in the
    ai_fit="strong" writes above, read live by GET /pipeline/today.

    Every step is isolated: a source failure is caught and recorded, a
    candidate failure is caught and recorded, and NEITHER aborts the rest of
    the run. Only a MorningRun that reaches "completed"/
    "completed_with_warnings" becomes eligible as the reference run for
    Today's "N new" count (see pipeline.service.today_summary) — a "failed"
    run is never used as that reference.
    """
    run = MorningRun(id=uuid.uuid4(), status="running")
    db.add(run)
    await db.commit()

    summary: dict = {"sources": {}, "candidates": {}}
    had_warning = False

    def record_source(name: str, outcome: dict) -> None:
        nonlocal had_warning
        summary["sources"][name] = outcome
        if outcome.get("status") == "error":
            had_warning = True

    try:
        summary["sources"]["linkedin"] = await linkedin_alert_sync_all(db, settings)
    except Exception as error:
        record_source("linkedin", {"status": "error", "error": str(error)[:500]})

    try:
        summary["sources"]["watchlist"] = await watchlist_all(db, settings)
    except Exception as error:
        record_source("watchlist", {"status": "error", "error": str(error)[:500]})

    for ats in sorted(REVERSE_SCAN_SOURCES):
        try:
            record_source(ats, await rotating_reverse_discovery(db, settings, ats))
        except Exception as error:
            record_source(ats, {"status": "error", "error": str(error)[:500]})

    users = list(await db.scalars(select(User).order_by(User.created_at)))
    for user in users:
        try:
            candidate_result = await _candidate_morning_cycle(db, settings, user, run.id)
        except Exception as error:
            candidate_result = {"status": "error", "error": str(error)[:500]}
            had_warning = True
        if candidate_result.get("ai_status") == "error" or (candidate_result.get("triage") or {}).get("status") == "error":
            had_warning = True
        summary["candidates"][str(user.id)] = candidate_result

    run.status = "completed_with_warnings" if had_warning else "completed"
    run.summary = summary
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()
    return {"run_id": str(run.id), "status": run.status, "summary": summary}


async def _run_agent(db: AsyncSession, user_id: uuid.UUID, settings: Settings, prompt: str, model: str):
    profile = await get_profile(db, user_id)
    workspace = await asyncio.to_thread(materialize_profile, user_id, profile, settings)
    process = await asyncio.create_subprocess_exec("claude", "-p", prompt, "--model", model, "--permission-mode", "acceptEdits", "--allowedTools", "Read,WebFetch,WebSearch,Write,Edit,Bash,Glob,Grep", "--disallowedTools", "MultiEdit,NotebookEdit,Task", cwd=workspace, env=candidate_environment(workspace), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=1200)
    return CommandResult(process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace"))
