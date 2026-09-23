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


def test_general_onboarding_derivation_from_profile_data():
    """No Dusan-specific code — this is what ANY candidate's onboarding
    produces from their own current_location/work_authorization."""
    config = build_location_config_from_profile("Madrid, Spain", ["Spain", "European Union"])
    assert config.home_country == "spain"
    assert config.home_city == "madrid"
    assert "europe" in config.eligible_regions
    assert "eea" in config.eligible_regions


def test_general_onboarding_derivation_without_broader_authorization():
    config = build_location_config_from_profile("Austin, United States", ["United States"])
    assert config.home_country == "united states"
    assert config.eligible_regions == frozenset()
    tier, _ = classify_location_eligibility("Remote - Germany", "", config)
    assert tier == "ineligible"
