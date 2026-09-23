"""Hosted AI Search (Phase 5 follow-up §2/§9) — replaces the local-CLI-only
Explore "AI Search" for portal (multi-user) mode with a direct, server-side
Anthropic API call using the REQUESTING candidate's own encrypted key and
chosen model (app.modules.ai_config). There is no shared/global credential
and no CLI/subprocess — Anthropic's native web_search tool runs the search
loop on Anthropic's side in one API call, and the model is asked to return
its findings as a small JSON array in its final response instead of writing
pipeline.md rows the way the local CLI-driven flow does.

Results flow through the exact same canonical pipeline as every other
discovery channel: ingest_discovery(method="web_search") -> canonical Job
-> add_candidate_job -> existing triage/Inbox/Today qualification. No
separate "manual vs automatic" job universe (Phase 5 §8).
"""

import json
import re

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.ai_config import service as ai_config_service
from app.modules.candidates.models import User
from app.modules.candidates.service import get_profile
from app.modules.discovery.sources import METHOD_WEB_SEARCH
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.schemas import CandidateJobCreate
from app.modules.pipeline.service import add_candidate_job

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Matches app.modules.discovery.sources.WEAK_SOURCES's "web-discovery" entry
# — an AI-search hit is a weak identity signal (like LinkedIn), never
# allowed to overwrite a strong ATS-sourced Job's canonical fields.
SOURCE_WEB_DISCOVERY = "web-discovery"
MAX_RESULTS = 10
_JSON_ARRAY_RE = re.compile(r"\[\s*\{.*\}\s*\]", re.DOTALL)


class AISearchNotConfigured(RuntimeError):
    """No CandidateAIConfig for this user — caller should surface a
    Munia-specific "AI Search isn't set up" message, not a raw provider error."""


class AISearchRateLimited(RuntimeError):
    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"try again in {retry_after_seconds:.0f}s")


def build_prompt(query: str, target_roles: list[str] | None) -> str:
    focus = f" The candidate is specifically targeting: {', '.join(target_roles)}." if target_roles else ""
    return (
        f'Search the web for real, currently open job postings matching: "{query}".{focus}\n\n'
        "Use web search to find ACTUAL live job postings with real URLs — never invent a company, title, or URL; "
        "if you are not confident a result is a real posting, leave it out.\n"
        f"Return AT MOST {MAX_RESULTS} results as a JSON array and nothing else after it, in exactly this shape:\n"
        '[{"company": "...", "title": "...", "location": "...", "url": "https://..."}]\n'
        "If you find no genuine postings, return []."
    )


def extract_job_candidates(response_text: str) -> list[dict]:
    match = _JSON_ARRAY_RE.search(response_text or "")
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)][:MAX_RESULTS]


async def run_ai_search(db: AsyncSession, settings: Settings, user: User, query: str) -> dict:
    """Returns an aggregate summary only (status/counts) — never the raw
    model response, search queries performed, or any per-candidate detail
    that isn't already implied by the resulting Job/CandidateJob rows."""
    config = await ai_config_service.get_ai_config(db, user.id)
    if config is None:
        raise AISearchNotConfigured("no AI provider configured for this candidate")

    remaining = ai_config_service.manual_search_cooldown_remaining(config)
    if remaining > 0:
        raise AISearchRateLimited(remaining)

    api_key = ai_config_service.decrypt_api_key(settings, config)
    profile = await get_profile(db, user.id)
    target_roles = ((profile.profile or {}).get("target_roles") or {}).get("primary") if profile else None

    payload = {
        "model": config.model,
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        "messages": [{"role": "user", "content": build_prompt(query, target_roles)}],
    }
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}

    # Marked before the call, not after: a candidate whose request hangs or
    # errors shouldn't be able to fire off a second one immediately, since
    # the cost (and their key's own rate limit) is already spent either way.
    await ai_config_service.mark_manual_search(db, config)
    await db.commit()

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(ANTHROPIC_API_URL, json=payload, headers=headers)
    except httpx.HTTPError as error:
        return {"status": "error", "error": f"AI provider request failed: {error}", "jobs_found": 0, "jobs_created": 0, "jobs_attached": 0}

    if response.status_code == 401:
        return {"status": "error", "error": "AI provider rejected the configured API key", "jobs_found": 0, "jobs_created": 0, "jobs_attached": 0}
    if response.status_code == 429:
        return {"status": "error", "error": "AI provider rate-limited this request — try again shortly", "jobs_found": 0, "jobs_created": 0, "jobs_attached": 0}
    if response.status_code != 200:
        return {"status": "error", "error": f"AI provider returned HTTP {response.status_code}", "jobs_found": 0, "jobs_created": 0, "jobs_attached": 0}

    body = response.json()
    text = "".join(block.get("text", "") for block in body.get("content", []) if isinstance(block, dict) and block.get("type") == "text")
    candidates = extract_job_candidates(text)

    jobs_created = 0
    jobs_attached = 0
    for candidate in candidates:
        url = str(candidate.get("url") or "").strip()
        title = str(candidate.get("title") or "").strip()
        company = str(candidate.get("company") or "").strip()
        if not url.startswith("http") or not title or not company:
            continue
        try:
            job_payload = JobIngest(company=company, title=title, location=str(candidate.get("location") or ""), source=SOURCE_WEB_DISCOVERY, posting_url=url, direct_application_url=url)
        except Exception:
            continue
        job, _, created = await ingest_discovery(db, job_payload, method=METHOD_WEB_SEARCH, user_id=user.id)
        jobs_created += int(created)
        # "uncertain" placeholder, exactly like every other discovery path
        # (linkedin_ingest/watchlist_scan/discovery.routes) — without it this
        # job would carry triage_result=None, which neither triage_all's
        # queue nor the Inbox/Today queries (INBOX_TRIAGE_RESULTS) recognize.
        await add_candidate_job(db, user.id, CandidateJobCreate(job_id=job.id, triage_result="uncertain", triage_reason="Added from AI Search; awaiting cheap triage"))
        jobs_attached += 1
    await db.commit()

    return {"status": "ok", "error": None, "jobs_found": len(candidates), "jobs_created": jobs_created, "jobs_attached": jobs_attached}
