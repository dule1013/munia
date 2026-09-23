import base64

from app.modules.discovery.linkedin_alerts import (
    LINKEDIN_ALERT_SENDER,
    extract_job_urls,
    is_authentic_sender,
    parse_alert_message,
    parse_alert_subject,
)


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def make_message(*, subject: str, body: str, from_header: str = f"LinkedIn Job Alerts <{LINKEDIN_ALERT_SENDER}>", dmarc: str = "dmarc=pass") -> dict:
    headers = [{"name": "Subject", "value": subject}, {"name": "From", "value": from_header}]
    if dmarc:
        headers.append({"name": "Authentication-Results", "value": f"mx.google.com; spf=pass; {dmarc}; dkim=pass"})
    return {"internalDate": "1758540000000", "payload": {"headers": headers, "body": {"data": b64(body)}}}


VALID_BODY = 'Check out this role: <a href="https://www.linkedin.com/jobs/view/3912345678?trk=email">Apply</a>'


def test_valid_alert_parses_one_job():
    message = make_message(subject="Acme Corp is hiring a Director of Engineering", body=VALID_BODY)
    candidates = parse_alert_message(message)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.job_id == "3912345678"
    assert c.url == "https://www.linkedin.com/jobs/view/3912345678"
    assert c.title == "Director of Engineering"
    assert c.company == "Acme Corp"


def test_multiple_jobs_in_one_alert():
    body = (
        'https://www.linkedin.com/comm/jobs/view/1111111111?trackingId=abc&refId=xyz '
        'https://www.linkedin.com/jobs/view/2222222222/ '
        'https://www.linkedin.com/jobs/search?currentJobId=3333333333&other=1'
    )
    message = make_message(subject="3 new Director of Engineering jobs for you", body=body)
    candidates = parse_alert_message(message)
    assert {c.job_id for c in candidates} == {"1111111111", "2222222222", "3333333333"}
    assert all(c.url.startswith("https://www.linkedin.com/jobs/view/") for c in candidates)
    # No anchor text in this fixture (bare URLs) — every job falls back to
    # the one subject-derived title, same as before this fix.
    assert all(c.title == "Director of Engineering" for c in candidates)


def test_digest_jobs_get_their_own_title_from_link_text_not_the_shared_subject():
    """Regression (production, 2026-09-22): a single "N new jobs for you"
    digest email produced N *distinct* real jobs, but every one of them was
    stamped with the same subject-derived title, making genuinely different
    postings look duplicated in the UI. Each job's own anchor text in the
    body must now win over the shared subject title."""
    body = (
        '<a href="https://www.linkedin.com/comm/jobs/view/1111111111?trk=digest">Head of Engineering, POS Platform at Moniepoint Group</a>'
        '<a href="https://www.linkedin.com/comm/jobs/view/2222222222?trk=digest">Engineering Manager (Remote) at Hire Feed</a>'
        '<a href="https://www.linkedin.com/comm/jobs/view/3333333333?trk=digest">Sr. Director &amp; Head of Architecture at G-P</a>'
    )
    message = make_message(subject="Director of Engineering and 2 other jobs for you", body=body)
    candidates = parse_alert_message(message)
    titles = {c.job_id: c.title for c in candidates}
    assert titles == {
        "1111111111": "Head of Engineering, POS Platform at Moniepoint Group",
        "2222222222": "Engineering Manager (Remote) at Hire Feed",
        "3333333333": "Sr. Director & Head of Architecture at G-P",
    }


def test_digest_job_with_only_generic_link_text_falls_back_to_subject_title():
    body = (
        '<a href="https://www.linkedin.com/comm/jobs/view/4444444444?trk=digest">Director of Engineering role</a>'
        '<a href="https://www.linkedin.com/comm/jobs/view/5555555555?trk=digest">Apply</a>'
    )
    message = make_message(subject="3 new Director of Engineering jobs for you", body=body)
    candidates = parse_alert_message(message)
    titles = {c.job_id: c.title for c in candidates}
    assert titles["4444444444"] == "Director of Engineering role"
    assert titles["5555555555"] == "Director of Engineering"  # generic "Apply" ignored, falls back


def test_image_link_to_a_job_does_not_clobber_its_own_text_link_title():
    # LinkedIn digests commonly wrap the same job in both an image link and
    # a text link; the longer, substantive text should win regardless of order.
    body = (
        '<a href="https://www.linkedin.com/comm/jobs/view/6666666666?trk=logo"><img src="logo.png" alt=""/></a>'
        '<a href="https://www.linkedin.com/comm/jobs/view/6666666666?trk=title">Head of Engineering, Platform</a>'
    )
    message = make_message(subject="2 new Head of Engineering jobs for you", body=body)
    candidates = parse_alert_message(message)
    assert len(candidates) == 1
    assert candidates[0].title == "Head of Engineering, Platform"


def test_normalized_url_strips_tracking_parameters():
    urls = extract_job_urls("https://www.linkedin.com/comm/jobs/view/9998887777?trk=flagship3_email&midToken=abc&trackingId=xyz")
    assert urls == [("9998887777", "https://www.linkedin.com/jobs/view/9998887777")]


def test_duplicate_urls_in_one_body_are_deduped():
    body = "https://www.linkedin.com/jobs/view/5551112222 and again https://www.linkedin.com/jobs/view/5551112222?trk=x"
    urls = extract_job_urls(body)
    assert urls == [("5551112222", "https://www.linkedin.com/jobs/view/5551112222")]


def test_subject_parsing_variants():
    assert parse_alert_subject("Acme Corp is hiring a Software Engineer") == ("Acme Corp", "Software Engineer")
    assert parse_alert_subject("3 new HR Coordinator jobs for you") == ("", "HR Coordinator")
    assert parse_alert_subject("New jobs for you: HR Coordinator, People Operations") == ("", "HR Coordinator")
    assert parse_alert_subject("") == ("", "")


def test_malformed_alert_with_no_job_url_yields_nothing():
    message = make_message(subject="Acme Corp is hiring a Director of Engineering", body="no links here at all")
    assert parse_alert_message(message) == []


def test_alert_with_unparseable_subject_yields_nothing():
    message = make_message(subject="", body=VALID_BODY)
    assert parse_alert_message(message) == []


def test_authentic_sender_requires_dmarc_pass_and_matching_domain():
    good = [{"name": "From", "value": f"LinkedIn <{LINKEDIN_ALERT_SENDER}>"}, {"name": "Authentication-Results", "value": "mx.google.com; dmarc=pass"}]
    assert is_authentic_sender(good) is True


def test_spoofed_sender_fails_without_dmarc():
    spoofed = [{"name": "From", "value": f"LinkedIn <{LINKEDIN_ALERT_SENDER}>"}, {"name": "Authentication-Results", "value": "mx.google.com; dmarc=fail"}]
    assert is_authentic_sender(spoofed) is False


def test_spoofed_sender_fails_with_lookalike_domain_even_if_dmarc_reported_pass():
    lookalike = [{"name": "From", "value": "LinkedIn <jobalerts-noreply@linkediin-mail.com>"}, {"name": "Authentication-Results", "value": "mx.google.com; dmarc=pass"}]
    assert is_authentic_sender(lookalike) is False


def test_missing_authentication_results_header_fails_closed():
    no_auth = [{"name": "From", "value": f"LinkedIn <{LINKEDIN_ALERT_SENDER}>"}]
    assert is_authentic_sender(no_auth) is False


def test_malformed_headers_shape_fails_closed_without_raising():
    assert is_authentic_sender(None) is False
    assert is_authentic_sender("not-a-list") is False
    assert is_authentic_sender([]) is False


# ── Plain-text card location extraction (job-enrichment audit, #3811) ──────
# Fixtures below are a sanitized reconstruction of the SHAPE observed in
# several real stored LinkedIn Job Alert digest emails (fictional
# company/title/tracking-param values) — LinkedIn's plain-text MIME
# alternative renders each job as a short, rigidly-ordered block that
# decode_message_body concatenates in alongside the HTML part:
#
#   --------------------------------------------------
#   {Title}
#   {Company}
#   {Location}
#   [0-2 optional badge lines]
#   View job: {url}
#
# with the first card preceded by "New jobs match your preferences."
# instead of a dashed rule. Location was previously never extracted at all
# (LinkedInJobCandidate.location defaulted to "" with no parsing logic).

PLAIN_TEXT_DIGEST = (
    "Your job alert for director of engineering in Spain\r\n"
    "New jobs match your preferences.\r\n"
    "\r\n"
    "Head of Engineering\r\n"
    "Acme Corp\r\n"
    "Barcelona\r\n"
    "\r\n"
    "This company is actively hiring\r\n"
    "View job: https://www.linkedin.com/comm/jobs/view/1111111111/?trackingId=abc%3D%3D\r\n"
    "\r\n"
    "---------------------------------------------------------\r\n"
    "  \r\n"
    "Head of AI Engineering\r\n"
    "Recruiter Agency Co\r\n"
    "Barcelona\r\n"
    "\r\n"
    "This company is actively hiring\r\n"
    "Apply with resume & profile\r\n"
    "View job: https://www.linkedin.com/comm/jobs/view/2222222222/?trackingId=def%3D%3D\r\n"
    "\r\n"
    "----------------------------------------------------------\r\n"
    "  \r\n"
    "Chief Engineer - Program X\r\n"
    "Some Group\r\n"
    "Madrid\r\n"
    "\r\n"
    "1 connection\r\n"
    "Apply with resume & profile\r\n"
    "View job: https://www.linkedin.com/comm/jobs/view/3333333333/?trackingId=ghi%3D%3D\r\n"
)

# The plain-text alternative usually sits alongside anchor'd HTML for the
# SAME jobs in a real multipart email; matching anchor text is what lets the
# parser trust the plain-text card without a mismatch. Kept intentionally
# simple/minimal here — full multipart assembly is exercised implicitly by
# make_message's single-part body, which is enough for decode_message_body.
PLAIN_TEXT_DIGEST_WITH_MATCHING_ANCHORS = PLAIN_TEXT_DIGEST + (
    '<a href="https://www.linkedin.com/comm/jobs/view/1111111111?trk=x">Head of Engineering</a>'
    '<a href="https://www.linkedin.com/comm/jobs/view/2222222222?trk=x">Head of AI Engineering</a>'
    '<a href="https://www.linkedin.com/comm/jobs/view/3333333333?trk=x">Chief Engineer - Program X</a>'
)


def test_plain_text_card_location_is_extracted_for_the_first_card_after_the_intro_line():
    message = make_message(subject="Acme Corp is hiring a Head of Engineering", body=PLAIN_TEXT_DIGEST_WITH_MATCHING_ANCHORS)
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["1111111111"].location == "Barcelona"
    assert candidates["1111111111"].company == "Acme Corp"  # anchor title matched -> company comes from the subject, not overridden


def test_plain_text_card_location_survives_a_recruitment_agency_company_name_with_a_dash():
    message = make_message(subject="3 new Head of Engineering jobs for you", body=PLAIN_TEXT_DIGEST_WITH_MATCHING_ANCHORS)
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["2222222222"].location == "Barcelona"
    assert candidates["2222222222"].title == "Head of AI Engineering"


def test_plain_text_card_location_extracted_after_a_dashed_separator_ignoring_trailing_badge_lines():
    message = make_message(subject="3 new Head of Engineering jobs for you", body=PLAIN_TEXT_DIGEST_WITH_MATCHING_ANCHORS)
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["3333333333"].location == "Madrid"
    assert candidates["3333333333"].title == "Chief Engineer - Program X"


def test_plain_text_card_is_not_trusted_when_the_anchor_title_disagrees():
    """A mismatch between the independently-derived anchor title and the
    plain-text card's own title is treated as a boundary-detection risk, not
    something to override — conservatively no location is attached."""
    mismatched = PLAIN_TEXT_DIGEST_WITH_MATCHING_ANCHORS.replace(
        '<a href="https://www.linkedin.com/comm/jobs/view/1111111111?trk=x">Head of Engineering</a>',
        '<a href="https://www.linkedin.com/comm/jobs/view/1111111111?trk=x">Totally Different Role Title</a>',
    )
    message = make_message(subject="3 new jobs for you", body=mismatched)
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["1111111111"].title == "Totally Different Role Title"
    assert candidates["1111111111"].location == ""


def test_plain_text_card_used_as_title_source_when_no_anchor_title_exists():
    message = make_message(subject="3 new jobs for you", body=PLAIN_TEXT_DIGEST)  # no HTML anchors at all this time
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["1111111111"].title == "Head of Engineering"
    assert candidates["1111111111"].location == "Barcelona"
    assert candidates["1111111111"].company == "Acme Corp"


def test_malformed_plain_text_card_with_too_few_lines_before_view_job_yields_no_location():
    body = "New jobs match your preferences.\r\nOnly One Line\r\nView job: https://www.linkedin.com/comm/jobs/view/4444444444/\r\n"
    message = make_message(subject="1 new job for you", body=body)
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["4444444444"].location == ""


def test_body_with_no_delimiter_at_all_yields_no_plain_text_cards_and_no_location():
    body = 'Head of Engineering\r\nAcme\r\nMadrid\r\nView job: https://www.linkedin.com/comm/jobs/view/5555555555/\r\n'
    message = make_message(subject="1 new job for you", body=body)
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["5555555555"].location == ""


def test_duplicate_job_id_across_two_plain_text_blocks_is_not_guessed_at():
    """Real digests never repeat a job_id across cards — if the boundary
    detection somehow produces that, treat it as a signal something went
    wrong rather than pick either block's location."""
    body = (
        "New jobs match your preferences.\r\n"
        "Title One\r\nCompany One\r\nMadrid\r\n"
        "View job: https://www.linkedin.com/comm/jobs/view/6666666666/\r\n"
        "----------------------------------------------------------\r\n"
        "Title Two\r\nCompany Two\r\nBarcelona\r\n"
        "View job: https://www.linkedin.com/comm/jobs/view/6666666666/\r\n"
    )
    message = make_message(subject="1 new job for you", body=body)
    candidates = {c.job_id: c for c in parse_alert_message(message)}
    assert candidates["6666666666"].location == ""
