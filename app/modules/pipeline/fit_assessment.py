"""Lightweight morning "is this worth Today?" assessment (Phase 5 follow-up
§F) — deliberately cheap and separate from the full, human-triggered
Evaluate action (Evaluation/fit_score/recommendation). Uses the candidate's
own configured AI provider/key/model (app.modules.ai_config); if the
candidate has none, this step is skipped entirely — never fabricated, never
blocking discovery/triage/Inbox.

Persisted on CandidateJob as ai_fit/ai_fit_reason/ai_fit_confidence/
ai_fit_assessed_at — never touching fit_score/recommendation/evaluated_at,
which remain exclusively the full Evaluate flow's fields.
"""

import json
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.ai_config import service as ai_config_service
from app.modules.ai_config.anthropic_client import call_anthropic
from app.modules.candidates.service import get_profile
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.service import has_candidate_decision

VALID_FIT = {"strong", "plausible", "reject"}
VALID_CONFIDENCE = {"high", "low"}
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class NoAIConfigured(RuntimeError):
    """The candidate has no CandidateAIConfig — caller should skip this
    job gracefully, not fail discovery/triage."""


def build_assessment_prompt(profile_summary: str, job: Job) -> str:
    return (
        "You are doing a QUICK, cheap screen of one job posting for a candidate — not a full evaluation.\n\n"
        f"Candidate summary:\n{profile_summary or '(no profile summary available)'}\n\n"
        f"Job: {job.title} at {job.company}\nLocation: {job.location or 'unspecified'}\n"
        f"Description:\n{(job.description or '(no description available)')[:4000]}\n\n"
        "Judge ONLY: does this genuinely match the candidate's target role/seniority/scope, and is there no hard "
        "disqualifying constraint (location/visa/etc.)? Be conservative — reserve \"strong\" for a clear, high-confidence match.\n"
        'Respond with ONLY a JSON object, no other text: {"fit": "strong"|"plausible"|"reject", "reason": "<one concise sentence>", "confidence": "high"|"low"}'
    )


def _profile_summary(profile_dict: dict) -> str:
    target_roles = ((profile_dict or {}).get("target_roles") or {}).get("primary") or []
    location = (profile_dict or {}).get("candidate", {}).get("location", "")
    parts = []
    if target_roles:
        parts.append(f"Target roles: {', '.join(target_roles)}")
    if location:
        parts.append(f"Location: {location}")
    return " | ".join(parts)


def parse_assessment(text: str) -> dict | None:
    match = _JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    fit = data.get("fit")
    confidence = data.get("confidence")
    if fit not in VALID_FIT or confidence not in VALID_CONFIDENCE:
        return None
    reason = str(data.get("reason") or "")[:500]
    return {"fit": fit, "reason": reason, "confidence": confidence}


async def assess_fit(db: AsyncSession, settings: Settings, item: CandidateJob, job: Job) -> dict | None:
    """Returns the parsed assessment dict, or None if it couldn't be
    produced (no AI configured, malformed model output, API failure) —
    None is never treated as "reject"; the caller simply leaves ai_fit
    unset and the job stays in Inbox pending a later, real assessment."""
    config = await ai_config_service.get_ai_config(db, item.user_id)
    if config is None:
        raise NoAIConfigured("candidate has no AI provider configured")

    profile = await get_profile(db, item.user_id)
    prompt = build_assessment_prompt(_profile_summary(profile.profile if profile else {}), job)

    result = await call_anthropic(settings, config, messages=[{"role": "user", "content": prompt}], max_tokens=300, timeout=30)
    if result.status != "ok":
        return None
    return parse_assessment(result.text)


async def apply_assessment(db: AsyncSession, item: CandidateJob, assessment: dict, *, run_id=None) -> None:
    """Persists the assessment — but never on a CandidateJob a human has
    already acted on (has_candidate_decision), matching the same
    triage-protection discipline as add_candidate_job (Checkpoint E §1).
    A "reject" result never deletes/hides an existing human-visible
    CandidateJob; it only means the item won't newly qualify for Today.

    `ai_fit_run_id` is set ONLY on a transition INTO "strong" (was not
    already "strong"), never on a reassessment that merely reconfirms an
    already-strong job — this is precisely what makes Today's "N new" count
    mean "newly qualified during the latest completed run", not "assessed
    recently". A job already strong from an earlier run stays tagged with
    THAT run even if today's cycle reassesses and reconfirms it.
    """
    if has_candidate_decision(item):
        return
    fit = assessment["fit"]
    confidence = assessment["confidence"]
    # Low confidence is never allowed to newly promote a job to "strong" —
    # downgrade it to "plausible" (stays in Inbox, doesn't reach Today)
    # rather than discarding the assessment outright.
    if fit == "strong" and confidence == "low":
        fit = "plausible"
    newly_strong = fit == "strong" and item.ai_fit != "strong"
    item.ai_fit = fit
    item.ai_fit_reason = assessment["reason"]
    item.ai_fit_confidence = confidence
    item.ai_fit_assessed_at = datetime.now(timezone.utc)
    if newly_strong:
        item.ai_fit_run_id = run_id
