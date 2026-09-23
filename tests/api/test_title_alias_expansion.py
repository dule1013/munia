"""Role-matching brittleness fix (Phase 5 follow-up §11): a candidate's
literal onboarding target-role phrases are widened with order-independent
AND-group variants so "Director of Engineering" isn't the ONLY phrasing
that matches — mirrors the "director + engineering" pattern career-ops
configs already write by hand.
"""

import yaml

from app.modules.candidates.schemas import OnboardingRequest
from app.modules.candidates.service import expand_title_aliases, portals_yaml


def test_director_of_engineering_gets_an_and_group_variant():
    expanded = expand_title_aliases(["Director of Engineering"])
    assert "Director of Engineering" in expanded
    assert "director + engineering" in [e.casefold() for e in expanded]


def test_vp_gets_a_vice_president_and_group_variant_too():
    expanded = expand_title_aliases(["VP of Engineering"])
    lowered = [e.casefold() for e in expanded]
    assert "vp + engineering" in lowered
    assert "vice president + engineering" in lowered


def test_acronym_alias_added_for_known_c_level_phrases():
    expanded = expand_title_aliases(["Chief Technology Officer"])
    assert "CTO" in expanded


def test_single_word_role_is_untouched():
    expanded = expand_title_aliases(["CTO"])
    assert expanded == ["CTO"]


def test_no_duplicate_entries_added():
    expanded = expand_title_aliases(["Director of Engineering", "Director of Engineering"])
    assert len(expanded) == len(set(e.casefold() for e in expanded))


def test_original_entries_always_preserved_verbatim():
    roles = ["Director of Engineering", "VP of Engineering", "Head of Engineering", "CTO"]
    expanded = expand_title_aliases(roles)
    for role in roles:
        assert role in expanded


def test_portals_yaml_uses_expanded_positive_list():
    data = OnboardingRequest(name="Test Candidate", master_cv="# CV", target_roles=["Director of Engineering"], current_location="Madrid, Spain", work_authorization=["Spain"], remote_preference="remote", relocation_preference="no")
    parsed = yaml.safe_load(portals_yaml(data))
    positive = [p.casefold() for p in parsed["title_filter"]["positive"]]
    assert "director of engineering" in positive
    assert "director + engineering" in positive
