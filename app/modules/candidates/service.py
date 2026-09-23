import json
import re
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


_STOPWORDS = {"of", "the", "a", "an"}
# The one level-word pair a literal-substring match cannot bridge on its
# own: "VP of Engineering" and "Vice President of Engineering" share no
# common word. Kept as a short, explicit map rather than a general synonym
# engine — title_filter's own AND-group ("word + word", any order) already
# handles every other case career-ops' own configs solve by hand today
# ("director + engineering" catches "Director of Engineering",
# "Engineering Director", "Director, Software Engineering", ...).
_LEVEL_ALIASES: dict[str, str] = {"vp": "vice president", "vice president": "vp"}
# Phrase <-> acronym aliases with no shared substring at all.
_ACRONYM_ALIASES: dict[str, str] = {
    "chief technology officer": "CTO",
    "chief executive officer": "CEO",
    "chief product officer": "CPO",
    "chief operating officer": "COO",
}


def _significant_words(phrase: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z]+", phrase.lower()) if w not in _STOPWORDS]


def expand_title_aliases(target_roles: list[str]) -> list[str]:
    """Widen a candidate's literal onboarding target-role phrases with
    order-independent AND-group variants (title-keywords.mjs's `"word +
    word"` syntax), so `positive: ["Director of Engineering"]` isn't
    limited to that one exact phrasing.

    Every original entry is kept verbatim and still matches exactly as
    before — this only ADDS entries, mirroring the AND-group pattern
    career-ops configs already write by hand (see portals.yml's own
    `"director + engineering"`) instead of requiring every candidate to
    discover and type that syntax themselves.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for role in target_roles:
        stripped = role.strip() if role else ""
        if stripped and stripped.casefold() not in seen:
            expanded.append(stripped)
            seen.add(stripped.casefold())

    def add(entry: str) -> None:
        if entry and entry.casefold() not in seen:
            expanded.append(entry)
            seen.add(entry.casefold())

    for role in target_roles:
        words = _significant_words(role)
        if len(words) >= 2:
            add(" + ".join(words))
            for index, word in enumerate(words):
                alias = _LEVEL_ALIASES.get(word)
                if alias:
                    swapped = list(words)
                    swapped[index] = alias
                    add(" + ".join(swapped))
        acronym = _ACRONYM_ALIASES.get(role.strip().casefold())
        if acronym:
            add(acronym)
    return expanded


def portals_yaml(data: OnboardingRequest) -> str:
    config = {
        "title_filter": {"positive": expand_title_aliases(data.target_roles), "negative": ["Junior", "Intern", "Individual Contributor", "Sales Engineer", "Solutions Engineer", "Field Engineer"]},
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
