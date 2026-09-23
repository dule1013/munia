"""Hosted (multi-user Munia) cheap candidate triage — replaces the CLI-agent
-based path (automation.batch.triage_all/_run_agent, which spawns `claude`
and needs a real candidate workspace + the CLI binary, absent from
Dockerfile.api on purpose) for the PRODUCTION morning cycle. Uses the exact
same candidate-Anthropic-key architecture as AI Search and the lightweight
fit assessment (app.modules.ai_config), via the shared
app.modules.ai_config.anthropic_client.call_anthropic call site.

Local/single-user Career Ops keeps its own CLI-based triage path
unchanged — automation.batch.triage_all/_run_agent are untouched and still
available (e.g. for `run_multi_user_automation.py triage` in an environment
where the CLI happens to be installed). This module is what the production
morning orchestrator actually calls instead.

Cheap triage is deliberately a BROAD reduction step — a short prompt, a
three-way bucket, no deep reasoning — kept conceptually distinct from the
lightweight fit assessment (app.modules.pipeline.fit_assessment), which is
itself already deliberately cheaper than the full Evaluate action. Do not
conflate the two rubrics.
"""

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.ai_config import service as ai_config_service
from app.modules.ai_config.anthropic_client import call_anthropic
from app.modules.candidates.service import get_profile
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.service import has_candidate_decision

VALID_TRIAGE_RESULTS = {"worth", "uncertain", "discard"}
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_triage_prompt(profile_summary: str, job: Job) -> str:
    return (
        "You are doing a QUICK, cheap first-pass triage of one job posting for a candidate — broad "
        "filtering to remove obvious weak matches, NOT a deep evaluation.\n\n"
        f"Candidate summary:\n{profile_summary or '(no profile summary available)'}\n\n"
        f"Job: {job.title} at {job.company}\nLocation: {job.location or 'unspecified'}\n"
        f"Description:\n{(job.description or '(no description available)')[:3000]}\n\n"
        'Judge only: "discard" if this is an obviously weak/irrelevant match (wrong seniority, wrong '
        'domain, a hard disqualifier); "worth" if it clearly matches the candidate\'s target role and '
        'seniority; "uncertain" if it genuinely needs a closer look. Be quick and broad, not thorough.\n'
        'Respond with ONLY a JSON object, no other text: {"result": "worth"|"uncertain"|"discard", "reason": "<one concise sentence>"}'
    )


def _profile_summary(profile_dict: dict) -> str:
    profile_dict = profile_dict or {}
    target_roles = ((profile_dict.get("target_roles") or {}).get("primary")) or []
    location = (profile_dict.get("candidate") or {}).get("location", "")
    parts = []
    if target_roles:
        parts.append(f"Target roles: {', '.join(target_roles)}")
    if location:
        parts.append(f"Location: {location}")
    return " | ".join(parts)


def parse_triage(text: str) -> dict | None:
    match = _JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    result = data.get("result")
    if result not in VALID_TRIAGE_RESULTS:
        return None
    reason = str(data.get("reason") or "")[:500]
    return {"result": result, "reason": reason}


async def triage_one_job(settings: Settings, config, profile_summary: str, job: Job):
    """Returns an AnthropicCallResult — callers decide what a non-"ok"
    status means for their own retry/stop semantics."""
    prompt = build_triage_prompt(profile_summary, job)
    return await call_anthropic(settings, config, messages=[{"role": "user", "content": prompt}], max_tokens=200, timeout=30)


async def triage_candidate_hosted(db: AsyncSession, settings: Settings, user_id) -> dict:
    """Hosted-triage counterpart to automation.batch._triage_one_candidate.
    Only ever touches a CandidateJob that (a) hasn't been really triaged yet
    (triaged_at IS NULL — never re-triages a rediscovered already-triaged
    job) and (b) has no human decision recorded. A "discard" result also
    hard-discards the item (pipeline_status="Discarded", skipped=True),
    matching the existing CLI-triage-path convention.

    A candidate with no AI configured is reported as "skipped_not_configured"
    — never an error, never a silent no-op that could be confused with "ran
    and found nothing". An unauthorized/rate-limited key stops processing
    THIS candidate's queue immediately (no fake triaged_at is ever written
    for the jobs it didn't get to) without touching any other candidate.
    """
    config = await ai_config_service.get_ai_config(db, user_id)
    if config is None:
        return {"status": "skipped_not_configured", "triaged": 0}

    profile = await get_profile(db, user_id)
    profile_summary = _profile_summary(profile.profile if profile else {})

    rows = await db.execute(
        select(CandidateJob, Job)
        .join(Job, Job.id == CandidateJob.job_id)
        .where(
            CandidateJob.user_id == user_id,
            CandidateJob.triaged_at.is_(None),
        )
    )

    triaged = 0
    skipped_errors = 0
    for item, job in rows.all():
        if has_candidate_decision(item) or item.eligibility == "ineligible":
            continue  # location gate already hard-discards ineligible jobs with triaged_at set; this only guards a job classified some other way
        result = await triage_one_job(settings, config, profile_summary, job)
        if result.status in ("unauthorized", "rate_limited"):
            await db.commit()
            return {"status": "error", "error": result.error, "triaged": triaged}
        if result.status != "ok":
            skipped_errors += 1
            continue  # transient/network error on this one job — try again next run, don't fake triaged_at
        parsed = parse_triage(result.text)
        if not parsed:
            skipped_errors += 1
            continue  # malformed model output — never stamp triaged_at on a guess
        item.triage_result = parsed["result"]
        item.triage_reason = parsed["reason"]
        item.triaged_at = datetime.now(timezone.utc)
        if parsed["result"] == "discard":
            item.pipeline_status = "Discarded"
            item.skipped = True
        triaged += 1

    await db.commit()
    if triaged == 0 and skipped_errors > 0:
        return {"status": "error", "error": "every triage attempt failed or returned malformed output", "triaged": 0}
    return {"status": "completed_with_warnings" if skipped_errors else "ok", "triaged": triaged, "skipped_errors": skipped_errors}
