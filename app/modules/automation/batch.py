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
from app.modules.candidates.service import get_profile
from app.modules.jobs.models import Job
from app.modules.migration.parsers import pipeline_rows, shortlist_rows
from app.modules.migration.service import import_pipeline
from app.modules.pipeline.models import CandidateJob


def list_values(value: object) -> list[str]:
    return [str(item).casefold() for item in value] if isinstance(value, list) else []


def relevant_to_candidate(job: Job, profile: CandidateProfile) -> bool:
    targets = list_values((profile.profile.get("target_roles") or {}).get("primary"))
    if targets and not any(target in job.title.casefold() or all(part in job.title.casefold() for part in target.split()) for target in targets):
        return False
    preferences = profile.profile.get("authorization") or {}
    locations = list_values(preferences.get("work_authorization"))
    location = job.location.casefold()
    return not locations or not location or "remote" in location or any(allowed in location for allowed in locations)


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
        await import_pipeline(db, representative, workspace)
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
        await import_pipeline(db, representative, workspace)
        after = len(list(await db.scalars(select(Job.id))))
        discovered += max(0, after - before)
    return {"discovered": discovered, "candidate_jobs": await populate_candidate_jobs(db), "unique_search_configs": len(groups)}


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
        await import_pipeline(db, user, settings.career_ops_workspace_root / str(user.id))
        completed += 1
    await populate_candidate_jobs(db)
    return {"users": len(users), "completed": completed}


async def _run_agent(db: AsyncSession, user_id: uuid.UUID, settings: Settings, prompt: str, model: str):
    profile = await get_profile(db, user_id)
    workspace = await asyncio.to_thread(materialize_profile, user_id, profile, settings)
    process = await asyncio.create_subprocess_exec("claude", "-p", prompt, "--model", model, "--permission-mode", "acceptEdits", "--allowedTools", "Read,WebFetch,WebSearch,Write,Edit,Bash,Glob,Grep", "--disallowedTools", "MultiEdit,NotebookEdit,Task", cwd=workspace, env=candidate_environment(workspace), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=1200)
    return CommandResult(process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace"))
