"""Candidate-specific relevance/eligibility over a shared, canonical Job.

Deliberately tiny and separate from both `automation` and `discovery` so
either can import it without a circular dependency: discovery's shared
scanning (Checkpoint D) needs to scope CandidateJob creation to a specific
set of candidates (a company's watchers), and automation's blanket
`populate_candidate_jobs` sweep needs the same predicate — neither module
should import the other just for this.

This is intentionally the SAME simple keyword/location heuristic used since
Checkpoint 4's `populate_candidate_jobs` — Phase 5 does not change how
relevance is computed, only which candidates it's applied to and when.
"""

from app.modules.candidates.models import CandidateProfile
from app.modules.jobs.models import Job


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
