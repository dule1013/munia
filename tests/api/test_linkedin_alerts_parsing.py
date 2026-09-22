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
