"""Pure parsing/validation for LinkedIn Job Alert emails (Phase 5 Checkpoint C).

No network I/O here — everything below takes already-fetched Gmail message
data and returns normalized job candidates or nothing. This is deliberately
adapted (not a straight port) from two existing career-ops building blocks:

- career-ops-plugin-linkedin-alerts (registered in plugins-registry/, pinned
  SHA de54949b) — its subject/body parsing (`parseSubject`, `extractJobUrls`)
  is genuinely good and is ported here. Its `ingest()` hook was NOT reused as
  a subprocess: it has no authenticity check on the sender at all, no
  structured output the FastAPI app could consume without either forking the
  CLI or writing Gmail credentials to a candidate's workspace .env — both
  unacceptable for a server-hosted multi-user app. See the Checkpoint C
  report for the full incompatibility writeup.
- the bundled plugins/gmail/_helpers.mjs `isAuthenticEmail` DMARC check,
  ported as `is_authentic_sender` below — the linkedin-alerts plugin has
  nothing equivalent, so this closes a real spoofing gap rather than just
  matching prior behavior.

Untrusted-content discipline (career-ops AGENTS.md "Untrusted External
Content"): an email body/subject is DATA. Nothing here executes, evaluates,
or is influenced by instruction-like text inside a message — we only ever
regex-extract a URL/company/title substring.
"""

import base64
import html
import re
from dataclasses import dataclass

LINKEDIN_ALERT_SENDER = "jobalerts-noreply@linkedin.com"

_JOB_URL_RE = re.compile(r"https://(?:www\.)?linkedin\.com/(?:comm/)?[^\s\"<>\]]+")
_JOB_ID_RE = re.compile(r"/jobs/view/(\d{7,})|[?&](?:currentJobId|jobId)=(\d{7,})")
# A LinkedIn "N new jobs for you" digest packs several DISTINCT job postings
# into one email with one generic subject line — parse_alert_subject can
# only ever produce one title for the whole message in that case. This
# pulls each job's OWN title from its anchor's visible link text in the
# body, which LinkedIn's templates set to the actual job title.
_ANCHOR_RE = re.compile(r'<a\b[^>]*\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_GENERIC_LINK_TEXT = {"apply", "apply now", "view job", "see job", "learn more", "view", "see more", ""}


@dataclass(frozen=True)
class LinkedInJobCandidate:
    job_id: str
    url: str
    title: str
    company: str
    location: str = ""


def is_authentic_sender(headers: list[dict], *, expected_sender: str = LINKEDIN_ALERT_SENDER) -> bool:
    """Fail-closed sender authenticity check.

    Two independent signals must both hold:
    1. DMARC alignment (`Authentication-Results` reports `dmarc=pass`) — the
       same check the bundled gmail plugin uses, ported here because the
       registered linkedin-alerts plugin has no equivalent.
    2. The `From` header's address domain is exactly `linkedin.com` (not a
       lookalike/subdomain trick) — defense in depth independent of DMARC,
       since DMARC only proves alignment with *some* domain the header claims.
    """
    if not isinstance(headers, list):
        return False
    dmarc_pass = False
    from_domain = ""
    for header in headers:
        name = str(header.get("name", "")).lower()
        value = str(header.get("value", ""))
        if name == "authentication-results" and re.search(r"dmarc=pass", value, re.IGNORECASE):
            dmarc_pass = True
        elif name == "from":
            match = re.search(r"@([\w.-]+)", value)
            if match:
                from_domain = match.group(1).lower()
    expected_domain = expected_sender.rsplit("@", 1)[-1].lower()
    return dmarc_pass and from_domain == expected_domain


def decode_message_body(payload: dict | None) -> str:
    """Recursively base64url-decode a Gmail message payload's body parts."""
    if not payload:
        return ""
    body = ""
    data = (payload.get("body") or {}).get("data")
    if data:
        padded = data.replace("-", "+").replace("_", "/")
        padded += "=" * (-len(padded) % 4)
        try:
            body += base64.b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            pass
    for part in payload.get("parts") or []:
        body += decode_message_body(part)
    return body


def get_header(message: dict, name: str) -> str:
    headers = (message.get("payload") or {}).get("headers") or []
    for header in headers:
        if str(header.get("name", "")).lower() == name.lower():
            return str(header.get("value", ""))
    return ""


def parse_alert_subject(subject: str) -> tuple[str, str]:
    """Returns (company, title). Ported from the linkedin-alerts plugin's
    `parseSubject` — LinkedIn's own alert phrasing, not something we control
    or can improve by guessing:
      "Acme Corp is hiring a Software Engineer"
      "3 new HR Coordinator jobs for you"
      "New jobs for you: HR Coordinator, People Operations"
    """
    if not subject:
        return "", ""
    match = re.match(r"^(.+?) is hiring (?:a |an )?(.+)$", subject, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.match(r"new (?:\w+ )?jobs? for you:?\s*(.+)$", subject, re.IGNORECASE)
    if match:
        return "", match.group(1).strip().split(",")[0].strip()
    match = re.match(r"^\d+ new (.+?) jobs?", subject, re.IGNORECASE)
    if match:
        return "", match.group(1).strip()
    return "", subject.strip()


def extract_job_urls(body: str) -> list[tuple[str, str]]:
    """Returns deduped [(job_id, normalized_url), ...] extracted from an
    alert body. Handles direct links (`/jobs/view/123`), the `comm/` tracking
    prefix, and `?currentJobId=`/`?jobId=` query forms — all normalized to
    the stable `linkedin.com/jobs/view/{id}` form with no tracking params."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _JOB_URL_RE.finditer(body or ""):
        url = match.group(0).replace("&amp;", "&").split('"')[0]
        id_match = _JOB_ID_RE.search(url)
        if not id_match:
            continue
        job_id = id_match.group(1) or id_match.group(2)
        clean_url = f"https://www.linkedin.com/jobs/view/{job_id}"
        if clean_url in seen:
            continue
        seen.add(clean_url)
        found.append((job_id, clean_url))
    return found


def _strip_tags(fragment: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", text).strip()


# LinkedIn's plain-text MIME alternative (present alongside the HTML part
# decode_message_body concatenates in) renders each job as a short, rigidly
# -ordered block — inspected directly against several real stored alert
# emails (career-ops job-enrichment audit) rather than assumed:
#
#     --------------------------------------------------
#     {Title}
#     {Company}
#     {Location}
#     [0-2 optional badge lines: "This company is actively hiring",
#      "Apply with resume & profile", "N connection(s)", a company
#      descriptor like "Fast growing", ...]
#     View job: {url}
#
# with the very first card preceded by "New jobs match your preferences."
# instead of a dashed rule. The badge-line vocabulary is deliberately NOT
# treated as a small closed set to skip (company descriptors vary too much
# to enumerate) — this only trusts the first three non-blank lines
# immediately after a delimiter, which held across every real card
# inspected; a card that doesn't fit that shape is left alone rather than
# guessed at.
_PLAIN_TEXT_DELIMITER_RE = re.compile(r"^-{10,}\s*$|^New jobs match your preferences\.\s*$", re.MULTILINE)
_VIEW_JOB_URL_RE = re.compile(r"View job:\s*(\S+)")


def _plain_text_job_cards(body: str) -> dict[str, dict[str, str]]:
    """{job_id: {"title", "company", "location"}} for cards whose plain-text
    block matched the expected 3-line shape. Never guesses: a block with
    fewer than 3 non-blank lines before its "View job:" line, or a job_id
    that (implausibly) appears in more than one block, is simply omitted."""
    if not body:
        return {}
    delimiter_ends = [m.end() for m in _PLAIN_TEXT_DELIMITER_RE.finditer(body)]
    if not delimiter_ends:
        return {}
    cards: dict[str, dict[str, str] | None] = {}
    for match in _VIEW_JOB_URL_RE.finditer(body):
        id_match = _JOB_ID_RE.search(match.group(1))
        if not id_match:
            continue
        job_id = id_match.group(1) or id_match.group(2)
        block_start = max((pos for pos in delimiter_ends if pos <= match.start()), default=None)
        if block_start is None:
            continue
        lines = [line.strip() for line in body[block_start : match.start()].splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        card = {"title": lines[0], "company": lines[1], "location": lines[2]}
        # A job_id appearing in more than one block is not something the
        # real digests examined ever did — if it somehow happens, that's a
        # sign of a boundary-detection error, not two genuine cards, so
        # tombstone it rather than keep either guess.
        cards[job_id] = None if job_id in cards else card
    return {job_id: card for job_id, card in cards.items() if card is not None}


def _normalize_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _per_job_link_titles(body: str) -> dict[str, str]:
    """Best-effort per-job title from each job link's own anchor text —
    the only thing in a multi-job digest that can distinguish one posting
    from another. Keeps the longest substantive text seen for a given job
    id (a digest often wraps the same job in both an image link and a text
    link); generic CTA text ("Apply", "View job") is ignored so a caller
    can tell "nothing useful here" apart from a real title."""
    best: dict[str, str] = {}
    for match in _ANCHOR_RE.finditer(body or ""):
        href, inner = match.group(1), match.group(2)
        id_match = _JOB_ID_RE.search(href)
        if not id_match:
            continue
        job_id = id_match.group(1) or id_match.group(2)
        text = _strip_tags(inner)
        if not text or text.lower() in _GENERIC_LINK_TEXT or len(text) < 4:
            continue
        if len(text) > len(best.get(job_id, "")):
            best[job_id] = text
    return best


def parse_alert_message(message: dict) -> list[LinkedInJobCandidate]:
    """The single entry point: a raw Gmail message dict in -> normalized job
    candidates out, or [] when there isn't enough to safely build one (no
    URLs, or a URL with no recognizable job id). Never fetches the LinkedIn
    page itself — only what the alert email already contains.

    A digest ("N new jobs for you") packs several distinct postings under
    one generic subject — every URL would otherwise get the SAME
    subject-derived title (the production bug this fixes). Each job's own
    anchor text in the body, when present, is used instead; the subject-
    derived title is only a fallback for whichever job (if any) has no
    usable link text of its own.
    """
    subject = get_header(message, "Subject")
    company, title = parse_alert_subject(subject)
    if not title:
        return []
    body = decode_message_body(message.get("payload"))
    urls = extract_job_urls(body)
    link_titles = _per_job_link_titles(body)
    plain_text_cards = _plain_text_job_cards(body)

    candidates = []
    for job_id, url in urls:
        anchor_title = link_titles.get(job_id)
        resolved_title = anchor_title or title
        resolved_company = company or "(LinkedIn)"
        location = ""
        card = plain_text_cards.get(job_id)
        if card:
            # Only trust the plain-text card's company/location when there's
            # no independently-derived anchor title that actually disagrees
            # with it — an anchor title is itself scoped to this exact URL,
            # so a mismatch is a signal the block-boundary detection above
            # picked up the wrong card for this job_id, not a reason to
            # override a title we already trust more.
            if anchor_title is None or _normalize_for_match(anchor_title) == _normalize_for_match(card["title"]):
                location = card["location"]
                if not anchor_title:
                    resolved_title = card["title"]
                if resolved_company == "(LinkedIn)" and card["company"]:
                    resolved_company = card["company"]
        candidates.append(LinkedInJobCandidate(job_id=job_id, url=url, title=resolved_title, company=resolved_company, location=location))
    return candidates
