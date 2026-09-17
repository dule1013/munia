import json
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.candidates.models import CandidateProfile, User
from app.modules.candidates.schemas import OnboardingRequest


async def get_user_by_clerk_id(db: AsyncSession, clerk_user_id: str) -> User | None:
    return await db.scalar(select(User).where(User.clerk_user_id == clerk_user_id))


async def bootstrap_user(db: AsyncSession, clerk_user_id: str, trusted_email: str, trusted_name: str) -> User:
    user = await get_user_by_clerk_id(db, clerk_user_id)
    if user is None:
        pending = await db.scalar(select(User).where(User.email == trusted_email, User.clerk_user_id.like("migration:%")))
        if pending:
            pending.clerk_user_id = clerk_user_id
            user = pending
    if user:
        if user.email != trusted_email or user.name != trusted_name:
            user.email = trusted_email
            user.name = trusted_name
        await db.commit()
        await db.refresh(user)
        return user
    user = User(clerk_user_id=clerk_user_id, email=trusted_email, name=trusted_name)
    db.add(user)
    await db.flush()
    db.add(CandidateProfile(user_id=user.id))
    await db.commit()
    await db.refresh(user)
    return user


MANAGED_PROFILE_START = "<!-- career-ops-portal-profile:start -->"
MANAGED_PROFILE_END = "<!-- career-ops-portal-profile:end -->"


def managed_profile_markdown(value: dict[str, Any]) -> str:
    candidate = value.get("candidate") or {}
    target_roles = (value.get("target_roles") or {}).get("primary") or []
    authorization = value.get("authorization") or {}
    preferences = value.get("preferences") or {}
    compensation = value.get("compensation") or {}
    roles = "\n".join(f"- {role}" for role in target_roles) or "- Not specified"
    work_authorization = ", ".join(str(item) for item in authorization.get("work_authorization") or []) or "Not specified"
    compensation_text = yaml.safe_dump(compensation, sort_keys=False, allow_unicode=True).strip() or "Not specified"
    return f"""## Portal-managed candidate preferences (authoritative)
{MANAGED_PROFILE_START}

- Name: {candidate.get('full_name') or 'Not specified'}
- Current location: {candidate.get('location') or 'Not specified'}

### Target roles
{roles}

### Authorization and mobility
- Work authorization: {work_authorization}
- Sponsorship required: {'yes' if authorization.get('sponsorship_required') else 'no'}
- Remote preference: {preferences.get('remote') or 'Not specified'}
- Relocation preference: {preferences.get('relocation') or 'Not specified'}

### Compensation
```yaml
{compensation_text}
```
{MANAGED_PROFILE_END}"""


def merge_managed_profile(existing: str, managed: str) -> str:
    start = existing.find(MANAGED_PROFILE_START)
    end = existing.find(MANAGED_PROFILE_END)
    if start != -1 and end > start:
        heading = existing.rfind("## Portal-managed candidate preferences (authoritative)", 0, start)
        replace_start = heading if heading != -1 else start
        return (existing[:replace_start].rstrip() + "\n\n" + managed + existing[end + len(MANAGED_PROFILE_END):]).strip() + "\n"
    return ((existing.rstrip() + "\n\n") if existing.strip() else "") + managed + "\n"


async def update_structured_profile(db: AsyncSession, profile: CandidateProfile, value: dict[str, Any]) -> CandidateProfile:
    profile.profile = value
    profile.profile_yaml = yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    profile.profile_markdown = merge_managed_profile(profile.profile_markdown, managed_profile_markdown(value))
    await db.commit()
    await db.refresh(profile)
    return profile


async def get_profile(db: AsyncSession, user_id) -> CandidateProfile:
    profile = await db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user_id))
    if not profile:
        profile = CandidateProfile(user_id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


def career_ops_profile(data: OnboardingRequest, trusted_email: str) -> dict[str, Any]:
    return {
        "candidate": {"full_name": data.name, "email": trusted_email, "location": data.current_location},
        "target_roles": {"primary": data.target_roles},
        "authorization": {"work_authorization": data.work_authorization, "sponsorship_required": data.sponsorship_required},
        "preferences": {"remote": data.remote_preference, "relocation": data.relocation_preference},
        "compensation": data.compensation,
        "language": {"output": "en", "modes_dir": "modes"},
        "spend_tier": "standard",
    }


def portals_yaml(data: OnboardingRequest) -> str:
    config = {
        "title_filter": {"positive": data.target_roles, "negative": ["Junior", "Intern", "Individual Contributor", "Sales Engineer", "Solutions Engineer", "Field Engineer"]},
        "location_filter": {"allow": list(dict.fromkeys([data.current_location, *data.work_authorization, "Remote"])), "always_allow": [data.current_location, "Remote"]},
        "tracked_companies": [],
        "generic_feeds": [],
        "search_queries": [{"name": f"{role} fresh roles", "query": f'"{role}" jobs', "enabled": True} for role in data.target_roles],
    }
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


async def complete_onboarding(db: AsyncSession, user: User, data: OnboardingRequest) -> CandidateProfile:
    profile = await get_profile(db, user.id)
    structured = career_ops_profile(data, user.email)
    profile.profile = structured
    profile.master_cv = data.master_cv
    profile.profile_yaml = yaml.safe_dump(structured, sort_keys=False, allow_unicode=True)
    profile.profile_markdown = merge_managed_profile(profile.profile_markdown, managed_profile_markdown(structured))
    profile.cv_facts = {"allow_metrics": [], "allow_facts": [], "forbidden_phrases": [], "warn_phrases": []}
    profile.portals_yaml = portals_yaml(data)
    profile.onboarding_complete = True
    await db.commit()
    await db.refresh(profile)
    return profile


def serialized_cv_facts(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"
