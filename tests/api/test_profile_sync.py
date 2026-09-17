import uuid

import yaml
from sqlalchemy import select

from app.modules.automation.workspace import materialize_profile
from app.modules.candidates.models import CandidateProfile, User


async def test_preference_change_updates_both_evaluation_contexts_and_preserves_custom_content(api):
    client, sessions, settings = api
    user = User(id=uuid.uuid4(), clerk_user_id="profile-user", email="profile@example.com", name="Profile User")
    authored = "# Candidate narrative\n\nI lead calm, high-accountability organizations.\n"
    custom = "# Custom workflow\n\nNever auto-apply.\n"
    async with sessions() as db:
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, profile={"candidate": {"location": "Madrid"}}, profile_yaml="candidate:\n  location: Madrid\n", profile_markdown=authored, custom_markdown=custom, cv_facts={}, master_cv="# CV"))
        await db.commit()

    updated = {
        "candidate": {"full_name": "Profile User", "location": "Barcelona"},
        "target_roles": {"primary": ["VP Engineering", "CTO"]},
        "authorization": {"work_authorization": ["Spain", "EU/EEA"], "sponsorship_required": False},
        "preferences": {"remote": "Remote preferred", "relocation": "EU only"},
        "compensation": {"target_range": "150000-180000", "currency": "EUR"},
    }
    response = await client.put("/api/v1/candidate/profile", headers={"x-test-clerk-user-id": "profile-user"}, json={"profile": updated})
    assert response.status_code == 200

    async with sessions() as db:
        profile = await db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
        assert yaml.safe_load(profile.profile_yaml) == updated
        assert authored.strip() in profile.profile_markdown
        assert "Current location: Barcelona" in profile.profile_markdown
        assert "- VP Engineering" in profile.profile_markdown
        assert "Work authorization: Spain, EU/EEA" in profile.profile_markdown
        assert profile.custom_markdown == custom
        (settings.career_ops_code_root / "modes").mkdir(parents=True)
        (settings.career_ops_code_root / "config").mkdir()
        workspace = materialize_profile(user.id, profile, settings)
        assert "Current location: Barcelona" in (workspace / "modes" / "_profile.md").read_text()
        assert (workspace / "modes" / "_custom.md").read_text() == custom
        assert yaml.safe_load((workspace / "config" / "profile.yml").read_text()) == updated
