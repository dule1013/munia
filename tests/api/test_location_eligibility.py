"""Three-tier location/residency eligibility (Phase 5 follow-up §D). All
cases use a Dusan-shaped config (Spain-based, Europe/EU/EEA/EMEA/Worldwide
eligible) since that's the concrete scenario driving this design, but
nothing here is Dusan-specific code — see build_location_config_from_profile
for the general onboarding derivation, tested separately below.
"""

from app.modules.candidates.location_eligibility import CandidateLocationConfig, build_location_config_from_profile, classify_location_eligibility

DUSAN = CandidateLocationConfig(home_country="spain", home_city="madrid", eligible_regions=frozenset({"europe", "eu", "european union", "eea", "european economic area", "emea", "worldwide", "global"}))


def classify(location: str, description: str = "") -> tuple[str, str]:
    return classify_location_eligibility(location, description, DUSAN)


def test_madrid_is_eligible():
    tier, _ = classify("Madrid")
    assert tier == "eligible"


def test_spain_is_eligible():
    tier, _ = classify("Spain")
    assert tier == "eligible"


def test_remote_spain_is_eligible():
    tier, _ = classify("Remote - Spain")
    assert tier == "eligible"


def test_europe_remote_is_plausible():
    tier, _ = classify("Europe Remote")
    assert tier == "plausible"


def test_eu_remote_is_plausible():
    tier, _ = classify("EU Remote")
    assert tier == "plausible"


def test_eea_remote_is_plausible():
    tier, _ = classify("EEA Remote")
    assert tier == "plausible"


def test_emea_remote_is_plausible():
    tier, _ = classify("EMEA Remote")
    assert tier == "plausible"


def test_worldwide_remote_is_plausible():
    tier, _ = classify("Worldwide Remote")
    assert tier == "plausible"


def test_bare_remote_is_plausible_not_rejected():
    tier, reason = classify("Remote")
    assert tier == "plausible"
    assert "ambiguous" in reason


def test_us_remote_is_ineligible():
    tier, _ = classify("US Remote")
    assert tier == "ineligible"


def test_us_only_is_ineligible():
    tier, _ = classify("US Only")
    assert tier == "ineligible"


def test_us_city_state_abbreviation_with_no_country_word_is_ineligible():
    """The exact gap found reviewing real production results: a bare "City,
    ST" location (common in US ATS postings) never spells out "United
    States" at all, so COUNTRY_ALIASES alone missed it and let it fall
    through to the "no signal" plausible default."""
    tier, reason = classify("Chicago, IL")
    assert tier == "ineligible"
    assert "united states" in reason


def test_us_city_full_state_name_with_no_country_word_is_ineligible():
    tier, _ = classify("Salem, New Hampshire")
    assert tier == "ineligible"


def test_us_city_state_abbreviation_plus_explicit_country_is_still_ineligible():
    tier, _ = classify("Cleveland, OH, United States")
    assert tier == "ineligible"


def test_a_two_letter_word_inside_description_prose_is_not_mistaken_for_a_state():
    """_names_a_us_state is scoped to comma-separated segments of the
    structured location field, not a bare substring search — "ok" appearing
    as an ordinary word in the description must never be treated as Oklahoma."""
    tier, _ = classify("Madrid, Spain", "The pace here is intense but the team culture is genuinely ok and supportive.")
    assert tier == "eligible"  # Madrid still wins; "ok" in the description is not OK-the-state


def test_multi_location_including_spain_alongside_a_us_state_is_still_eligible():
    tier, _ = classify("Madrid, Spain or Austin, TX")
    assert tier == "eligible"


def test_uk_only_is_ineligible():
    tier, _ = classify("UK Only")
    assert tier == "ineligible"


def test_germany_only_is_ineligible():
    tier, _ = classify("Germany Only")
    assert tier == "ineligible"


def test_emea_with_explicit_german_residency_requirement_is_ineligible():
    """The critical precedence case: a broad "EMEA" scope descriptor must
    NOT win over an explicit, more specific residency requirement."""
    tier, reason = classify("Remote EMEA", "This role requires candidates to reside in Germany for tax purposes.")
    assert tier == "ineligible"
    assert "germany" in reason.lower()


def test_europe_with_spain_and_portugal_named_is_eligible():
    tier, _ = classify("Europe", "Open to candidates in Spain and Portugal.")
    assert tier == "eligible"


def test_multi_location_including_spain_is_eligible():
    tier, _ = classify("Remote - Spain, France, Italy")
    assert tier == "eligible"


def test_multi_location_excluding_spain_is_ineligible():
    tier, _ = classify("Remote - France, Germany, Italy")
    assert tier == "ineligible"


def test_contradictory_location_field_vs_jd_residency_requirement():
    """Location says "Europe" but the JD text carries an explicit residency
    requirement for a different, ineligible country — the requirement wins."""
    tier, reason = classify("Remote - Europe", "Employees must reside in France for this role.")
    assert tier == "ineligible"
    assert "france" in reason.lower()


def test_no_location_information_is_plausible_not_rejected():
    tier, reason = classify("", "")
    assert tier == "plausible"
    assert "no location" in reason


def test_home_country_named_via_residency_requirement_is_eligible():
    tier, _ = classify("Remote", "Candidates must reside in Spain.")
    assert tier == "eligible"


def test_general_onboarding_derivation_from_simple_profile_shape():
    """No Dusan-specific code — this is what a freshly onboarded candidate's
    simpler profile shape (candidate.location + authorization.work_authorization)
    produces, before any richer location block exists."""
    profile = {"candidate": {"location": "Madrid, Spain"}, "authorization": {"work_authorization": ["Spain", "European Union"]}}
    config = build_location_config_from_profile(profile)
    assert config.home_country == "spain"
    assert config.home_city == "madrid"
    assert "europe" in config.eligible_regions
    assert "eea" in config.eligible_regions


def test_general_derivation_prefers_the_richer_location_block_when_present():
    """Matches production's actual profile shape (verified against Dusan's
    real CandidateProfile) — location.country/city/authorized_in, not the
    simpler onboarding-only shape."""
    profile = {
        "location": {"city": "Madrid", "country": "Spain", "authorized_in": ["Spain", "European Union", "European Economic Area", "Serbia"]},
        "candidate": {"location": "Madrid, Spain"},
    }
    config = build_location_config_from_profile(profile)
    assert config.home_country == "spain"
    assert config.home_city == "madrid"
    assert config.eligible_regions == frozenset({"eu", "european union", "eea", "european economic area", "europe", "emea", "worldwide", "global"})


def test_worldwide_and_global_are_always_eligible_regions_by_default():
    """Deliberately universal, not Dusan-specific: these two terms are as
    broad as a remote-scope claim gets, and the classifier only ever treats
    an eligible region as "plausible" (never outright "eligible"), so
    including them by default can't manufacture false certainty."""
    profile = {"candidate": {"location": "Austin, United States"}, "authorization": {"work_authorization": ["United States"]}}
    config = build_location_config_from_profile(profile)
    assert config.eligible_regions == frozenset({"worldwide", "global"})


def test_general_onboarding_derivation_without_broader_authorization():
    profile = {"candidate": {"location": "Austin, United States"}, "authorization": {"work_authorization": ["United States"]}}
    config = CandidateLocationConfig(home_country="united states", home_city="austin", eligible_regions=frozenset())
    assert config.home_country == "united states"
    tier, _ = classify_location_eligibility("Remote - Germany", "", config)
    assert tier == "ineligible"
