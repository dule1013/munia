"""Deterministic, three-tier location/residency eligibility (Phase 5
follow-up §D). No LLM call for a basic location check — a candidate's own
AI triage can resolve genuinely ambiguous cases later using the full JD;
this module exists to handle everything that doesn't actually need that.

Three tiers, deliberately not a boolean pass/fail:
  - "eligible"   — the candidate's own location/region is named, or an
                    explicit residency requirement names a place the
                    candidate is eligible under.
  - "plausible"  — a broad remote-region term (Europe/EU/EEA/EMEA/
                    Worldwide/Global) or a bare "Remote"/"Distributed" with
                    no country signal at all. Not proof, not a reject —
                    stays actionable in the Inbox pending real triage.
  - "ineligible" — an explicit residency requirement or a specific
                    single-country remote scope naming somewhere the
                    candidate is NOT eligible under, with no eligible
                    region/country also present.

Precedence (highest first): an explicit residency-REQUIREMENT phrase
("must reside in X", "X only", "candidates in X") is a much stronger,
more specific signal than a general scope descriptor, and is checked
first — "Remote EMEA, must reside in Germany" is ineligible for a Spain
-based candidate even though "EMEA" alone would be merely plausible.
"""

import re
from dataclasses import dataclass, field

EligibilityTier = str  # "eligible" | "plausible" | "ineligible"

# Broad remote-region terms that widen scope without naming a specific
# country. Word-boundary matched (see _contains_term) so short abbreviations
# like "eu"/"us" never match inside another word ("Peru", "focus").
REGION_TERMS: frozenset[str] = frozenset({"europe", "european union", "eu", "eea", "european economic area", "emea", "worldwide", "global", "anywhere"})

# Generic remote/distributed wording with no geography attached at all.
AMBIGUOUS_REMOTE_TERMS: frozenset[str] = frozenset({"remote", "distributed", "work from anywhere", "fully remote"})

# Recognized country names/abbreviations -> canonical token. Extend this
# list as needed; it is intentionally NOT specific to any one candidate.
COUNTRY_ALIASES: dict[str, str] = {
    "united states": "united states", "usa": "united states", "u.s.": "united states", "us": "united states",
    "united kingdom": "united kingdom", "uk": "united kingdom", "u.k.": "united kingdom",
    "germany": "germany", "france": "france", "italy": "italy", "portugal": "portugal",
    "spain": "spain", "canada": "canada", "ireland": "ireland", "netherlands": "netherlands",
    "poland": "poland", "serbia": "serbia",
}

# US ATS postings very commonly give a "City, ST" / "City, State" location
# (e.g. "Chicago, IL", "Salem, New Hampshire") WITHOUT ever spelling out
# "United States" at all — COUNTRY_ALIASES alone misses this entirely,
# which was letting these fall through to the "no clear signal -> plausible"
# default instead of being recognized as US-scoped.
US_STATE_ABBREVIATIONS: frozenset[str] = frozenset({
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
    "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
    "va", "wa", "wv", "wi", "wy", "dc",
})
US_STATE_NAMES: frozenset[str] = frozenset({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming",
})


def _names_a_us_state(text: str) -> bool:
    """Deliberately scoped to comma-separated SEGMENTS of `text` (the
    structured job `location` field, or a short residency-requirement
    fragment) rather than a bare substring search across free text — a
    bare 2-letter state code ("OK", "IN", "OR", "ME", "PA", "WA") would
    false-positive constantly inside description prose, but is unambiguous
    as its own comma-delimited segment ("Chicago, IL") or as an entire
    short captured fragment ("must reside in Illinois" -> "Illinois")."""
    for segment in (text or "").split(","):
        token = segment.strip().lower()
        if token in US_STATE_ABBREVIATIONS or token in US_STATE_NAMES:
            return True
    return False


# Explicit residency-REQUIREMENT phrasing — a much stronger signal than a
# bare region/country mention elsewhere in the text. Captures the place
# named right after the phrase.
_RESIDENCY_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"must (?:be based|reside|be located|live) in (?:the )?([a-z .]+?)(?:[.,;]|$)",
        r"candidates? (?:must be |should be |need to be )?(?:based|located|residing) in (?:the )?([a-z .]+?)(?:[.,;]|$)",
        # Catches phrasing that doesn't use "must"/"candidates" directly
        # ("requires you to reside in X", "you will need to reside in X") —
        # "reside/live in X" alone is already an unambiguous residency signal.
        r"(?:reside|live) in (?:the )?([a-z .]+?)(?:[.,;]|$)",
        r"open (?:only )?to (?:residents|candidates) (?:of|in) (?:the )?([a-z .]+?)(?:[.,;]|$)",
        r"([a-z .]+?)[- ]based candidates? only",
        r"([a-z .]+?) only\b",
        r"only (?:in|from) (?:the )?([a-z .]+?)(?:[.,;]|$)",
    )
)


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text) is not None


def _resolve_countries(fragment: str) -> set[str]:
    """Every country named in `fragment`, not just the first alias that
    happens to appear earliest in COUNTRY_ALIASES — a fragment like "Spain
    and Portugal" must be checked against ALL of them so the candidate's
    own country is recognized even when another country is also listed."""
    fragment = fragment.strip().strip(".")
    countries = {canonical for alias, canonical in COUNTRY_ALIASES.items() if _contains_term(fragment, alias)}
    if _names_a_us_state(fragment):
        countries.add("united states")
    return countries


def _resolve_regions(fragment: str) -> set[str]:
    return {term for term in REGION_TERMS if _contains_term(fragment, term)}


@dataclass(frozen=True)
class CandidateLocationConfig:
    """What "eligible" means for one candidate — general, not Dusan-specific.
    `home_country`/`home_city` are the clearest positive signal; `eligible_regions`
    are the broader remote-region terms (from REGION_TERMS) the candidate would
    also plausibly work under (e.g. a Spain-based candidate listing "europe",
    "eu", "eea", "emea", "worldwide")."""

    home_country: str = ""
    home_city: str = ""
    eligible_regions: frozenset[str] = field(default_factory=frozenset)

    def names_candidate(self, text: str) -> bool:
        return (bool(self.home_city) and _contains_term(text, self.home_city.lower())) or (bool(self.home_country) and _contains_term(text, self.home_country.lower()))

    def is_eligible_region(self, region: str) -> bool:
        return region in self.eligible_regions


def classify_location_eligibility(location: str, description: str, config: CandidateLocationConfig) -> tuple[EligibilityTier, str]:
    text = f"{location or ''} {description or ''}".lower()
    if not text.strip():
        return "plausible", "no location information available"

    # 1. Explicit residency REQUIREMENT — highest precedence, overrides any
    # broader scope term found elsewhere in the same text.
    for pattern in _RESIDENCY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        fragment = match.group(1)
        countries = _resolve_countries(fragment)
        if countries:
            if config.home_country.lower() in countries:
                return "eligible", f"explicit residency requirement includes candidate's country ({', '.join(sorted(countries))})"
            return "ineligible", f"explicit residency requirement excludes candidate ({', '.join(sorted(countries))} required)"
        regions = _resolve_regions(fragment)
        if regions:
            if any(config.is_eligible_region(r) for r in regions):
                return "eligible", f"explicit residency requirement matches an eligible region ({', '.join(sorted(regions))})"
            return "plausible", f"explicit residency requirement names a region not in candidate's eligible list ({', '.join(sorted(regions))})"

    # 2. Candidate's own city/country named anywhere -> eligible.
    if config.names_candidate(text):
        return "eligible", "candidate's own location is named"

    # 3. A specific, named foreign country with no eligible region/country
    # also present -> ineligible (implicit country-scoped remote, e.g. "US
    # remote", "Remote (Germany)", "Remote — UK, Germany, France").
    named_countries = {alias_country for alias, alias_country in COUNTRY_ALIASES.items() if _contains_term(text, alias)}
    if _names_a_us_state(location):
        named_countries.add("united states")
    named_countries.discard(config.home_country.lower())
    has_eligible_region = any(config.is_eligible_region(r) for r in REGION_TERMS if _contains_term(text, r))
    if named_countries and not has_eligible_region:
        return "ineligible", f"location scoped to {', '.join(sorted(named_countries))}, not in candidate's eligible set"

    # 4. A broad eligible region term, no contradicting country -> plausible.
    if has_eligible_region:
        return "plausible", "regionally plausible (broad remote-region term, no contradicting residency signal)"

    # 5. Bare "Remote"/"Distributed" with no geography at all -> plausible/ambiguous.
    if any(_contains_term(text, term) for term in AMBIGUOUS_REMOTE_TERMS):
        return "plausible", "ambiguous — remote with no geographic signal"

    # 6. No signal at all -> don't penalize missing data.
    return "plausible", "no clear geographic signal"


def build_location_config_from_profile(profile: dict) -> CandidateLocationConfig:
    """General derivation from a CandidateProfile.profile dict (Phase 5
    follow-up §D) — no candidate-specific hardcoding. Reads whichever shape
    is actually present:

    - the richer `location: {country, city, authorized_in: [...]}` block
      (what a fleshed-out production profile carries — e.g. Dusan's:
      `authorized_in: ["Spain", "European Union", "European Economic Area",
      "Serbia"]`), preferred when present; or
    - the simpler shape today's portal onboarding produces
      (`candidate.location: "City, Country"` + `authorization.
      work_authorization: [...]`), as a fallback for a freshly onboarded
      candidate with no richer location block yet.

    `authorized_in`/`work_authorization` entries that name a known
    REGION_TERMS group are folded into eligible_regions, with EU/EEA
    authorization additionally implying the EMEA/Europe siblings a job
    posting might use instead of the exact phrase the candidate typed.
    "worldwide"/"global" are ALWAYS included: those two terms are about as
    broad as a remote-scope claim gets, and classify_location_eligibility
    already treats an eligible broad-region term as merely "plausible" (not
    "eligible" outright) — so this never manufactures false certainty, it
    only keeps a "Worldwide remote" posting from being needlessly penalized
    for lacking an explicit region match.
    """
    location_block = profile.get("location") or {}
    home_country = str(location_block.get("country") or "").strip().lower()
    home_city = str(location_block.get("city") or "").strip().lower()
    authorized_in = list(location_block.get("authorized_in") or [])

    if not home_country:
        candidate_location = str((profile.get("candidate") or {}).get("location") or "")
        parts = [p.strip().lower() for p in candidate_location.split(",") if p.strip()]
        home_city = home_city or (parts[0] if len(parts) >= 2 else "")
        home_country = parts[-1] if parts else ""
        if not authorized_in:
            authorized_in = list((profile.get("authorization") or {}).get("work_authorization") or [])

    eligible_regions: set[str] = {"worldwide", "global"}
    for entry in authorized_in:
        lowered = str(entry).strip().lower()
        regions = _resolve_regions(lowered)
        eligible_regions.update(regions)
        # "European Union"/"EEA" authorization plausibly also covers the
        # sibling region terms (including EMEA) a job posting might use instead.
        if regions & {"eu", "european union", "eea", "european economic area"}:
            eligible_regions.update({"eu", "european union", "eea", "european economic area", "europe", "emea"})

    return CandidateLocationConfig(home_country=home_country, home_city=home_city, eligible_regions=frozenset(eligible_regions))
