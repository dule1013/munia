"""Static catalog of discovery sources/methods (Phase 5 §1/§6).

This is deliberately NOT a database table — it's a small, code-reviewed
registry the UI and automation layers can grow into, matching the underlying
Career Ops engine's real capabilities rather than every provider module that
happens to exist under providers/.

Two axes matter and must not be conflated:

- `source`  — WHERE a job posting lives: linkedin, greenhouse, lever, ashby,
  workday, teamtailor, workable, ...
- `method`  — HOW Munia found it: reverse_ats (a full public-network scan,
  no company list needed), company_watchlist (a known-company scan),
  email_alert (LinkedIn Job Alerts via Gmail), web_search (AI discovery),
  manual (a candidate/AI-added offer), legacy_import (one-time migration
  backfill).

`REVERSE_SCAN_SOURCES` is intentionally a short, verified list. Career Ops
vendors ~90 provider modules, but only a handful expose a full public
company-network dataset that scan-ats-full.mjs can walk with no candidate
-supplied company list — the rest (Teamtailor, Workable, SmartRecruiters,
Recruitee, Personio, Pinpoint, BambooHR, Breezy, Comeet, ...) only ever work
against a KNOWN company (the Company Watchlist / portals.yml
tracked_companies). Do not add a provider here just because providers/<id>.mjs
exists — verify it has a reverse-network dataset (scan-ats-full.mjs's
`SOURCES` map) and that it passes its own tests first.
"""

from dataclasses import dataclass

CATEGORY_NETWORK_SCAN = "network_scan"
CATEGORY_LINKEDIN_ALERTS = "linkedin_alerts"
CATEGORY_COMPANY_WATCHLIST = "company_watchlist"
CATEGORY_JOB_FEED = "job_feed"
CATEGORY_WEB_DISCOVERY = "web_discovery"

METHOD_REVERSE_ATS = "reverse_ats"
METHOD_COMPANY_WATCHLIST = "company_watchlist"
METHOD_EMAIL_ALERT = "email_alert"
METHOD_WEB_SEARCH = "web_search"
METHOD_MANUAL = "manual"
METHOD_LEGACY_IMPORT = "legacy_import"
# scan.mjs today reads tracked_companies + job_boards + search_queries out of
# portals.yml in one pass — a mix of watchlist and job-feed discovery that
# isn't yet split into its own automation paths (that split is Checkpoint D:
# a dedicated Company Watchlist scan). Labelled distinctly rather than
# overloading METHOD_COMPANY_WATCHLIST for a scan that isn't only watchlist.
METHOD_DIRECT_SCAN = "direct_scan"

# Verified against this checkout on 2026-09-22: each provider's own unit
# tests pass AND a live `node scan-ats-full.mjs --ats <id> --dry-run` sample
# resolved its network dataset with datasetStatus "ok" and returned real
# postings. iCIMS is included on that basis (Phase 5 §1 item 5) — it was not
# previously exposed in SUPPORTED_ATS/the Explore UI and stays gated there
# until Checkpoint D/E wires it through end-to-end.
REVERSE_SCAN_SOURCES: frozenset[str] = frozenset({"greenhouse", "lever", "ashby", "workday", "icims"})

# Real ATS providers in Career Ops that have NO full-network public dataset —
# they only ever return results for a company the candidate has told us
# about (Company Watchlist / portals.yml tracked_companies). Listed here so
# the future watchlist UI can offer "detected provider" without silently
# implying reverse-network coverage that doesn't exist.
WATCHLIST_ONLY_SOURCES: frozenset[str] = frozenset({
    "teamtailor", "workable", "smartrecruiters", "recruitee", "personio",
    "pinpoint", "bamboohr", "breezy", "comeet",
})

# Sources that do not carry their own stable, per-posting canonical URL we can
# trust as a strong identity signal (an inbox forward, a search-engine result,
# an unlabeled import). Used by jobs.service's conservative cross-source
# dedup: a Job first (or only) seen through one of these can be matched onto
# an existing STRONG-sourced Job, but never the reverse — a weak observation
# never overwrites a strong Job's canonical identity.
WEAK_SOURCES: frozenset[str] = frozenset({"linkedin", "web-discovery", "unknown"})


@dataclass(frozen=True)
class DiscoverySource:
    id: str
    label: str
    category: str
    reverse_scan_capable: bool = False


def _label(source_id: str) -> str:
    overrides = {"smartrecruiters": "SmartRecruiters", "bamboohr": "BambooHR", "icims": "iCIMS"}
    return overrides.get(source_id, source_id.title())


SOURCE_CATALOG: dict[str, DiscoverySource] = {
    **{s: DiscoverySource(s, _label(s), CATEGORY_NETWORK_SCAN, reverse_scan_capable=True) for s in REVERSE_SCAN_SOURCES},
    **{s: DiscoverySource(s, _label(s), CATEGORY_COMPANY_WATCHLIST) for s in WATCHLIST_ONLY_SOURCES},
    "linkedin": DiscoverySource("linkedin", "LinkedIn Job Alerts", CATEGORY_LINKEDIN_ALERTS),
    "web-discovery": DiscoverySource("web-discovery", "Web Discovery", CATEGORY_WEB_DISCOVERY),
}


def is_reverse_scan_capable(source: str) -> bool:
    return source in REVERSE_SCAN_SOURCES


def is_weak_source(source: str) -> bool:
    return source in WEAK_SOURCES


# Hostname patterns for auto-detecting a watched company's ATS provider from
# its careers_url, mirroring the auto-detect patterns already used by
# providers/*.mjs and scan-ats-full.mjs. Detection-only (no network call) —
# actual scanning/tenant verification is a Checkpoint C/D concern.
#
# `path` boards keep the tenant slug in the URL path (host is shared across
# every tenant); `subdomain` boards key the tenant off the leftmost label of
# a per-tenant subdomain. iCIMS additionally prefixes that label with
# "careers-", stripped separately below.
_PATH_BASED_HOSTS: tuple[tuple[str, str], ...] = (
    (".greenhouse.io", "greenhouse"),
    (".lever.co", "lever"),
    ("jobs.ashbyhq.com", "ashby"),
    ("apply.workable.com", "workable"),
    ("jobs.smartrecruiters.com", "smartrecruiters"),
)
_SUBDOMAIN_BASED_HOSTS: tuple[tuple[str, str], ...] = (
    (".myworkdayjobs.com", "workday"),
    (".teamtailor.com", "teamtailor"),
    (".recruitee.com", "recruitee"),
    (".jobs.personio.de", "personio"),
    (".jobs.personio.com", "personio"),
    (".pinpointhq.com", "pinpoint"),
    (".bamboohr.com", "bamboohr"),
    (".breezy.hr", "breezy"),
    (".icims.com", "icims"),
)
# Custom/opaque domains where a slug can't be reliably read off the URL —
# provider is still worth surfacing, tenant is left for the candidate to fill in.
_NO_TENANT_HOSTS: tuple[tuple[str, str], ...] = (
    ("smartrecruiters.com", "smartrecruiters"),
    ("comeet.com", "comeet"),
)


def detect_provider(careers_url: str) -> tuple[str | None, str | None]:
    """Best-effort (provider, tenant_slug) guess from a careers URL's host.

    Detection only — no network request. `tenant_slug` is the first path
    segment for path-based boards (e.g. jobs.ashbyhq.com/<slug>) or the
    leftmost subdomain label for subdomain-based boards (e.g.
    <slug>.recruitee.com); either may be None when it can't be inferred.
    """
    from urllib.parse import urlsplit

    if not careers_url:
        return None, None
    parsed = urlsplit(careers_url if "//" in careers_url else f"https://{careers_url}")
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if not host:
        return None, None

    for suffix, provider in _PATH_BASED_HOSTS:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            path_parts = [part for part in parsed.path.split("/") if part]
            return provider, (path_parts[0] if path_parts else None)

    for suffix, provider in _SUBDOMAIN_BASED_HOSTS:
        if host.endswith(suffix) and host != suffix.lstrip("."):
            label = host[: -len(suffix)]
            tenant = label.rsplit(".", 1)[-1] if label else None
            if provider == "icims" and tenant and tenant.startswith("careers-"):
                tenant = tenant[len("careers-") :]
            return provider, tenant or None

    for suffix, provider in _NO_TENANT_HOSTS:
        if host == suffix or host.endswith(f".{suffix}"):
            return provider, None

    return None, None
