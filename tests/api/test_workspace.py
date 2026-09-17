import uuid

import pytest

from app.core.config import Settings
from app.modules.automation.workspace import candidate_environment, materialize_profile, workspace_for
from app.modules.candidates.models import CandidateProfile


def settings(tmp_path):
    code = tmp_path / "code"
    (code / "modes").mkdir(parents=True)
    (code / "config").mkdir()
    (code / "modes" / "oferta.md").write_text("system mode")
    (code / "config" / "profile.example.yml").write_text("system config")
    (code / "verify-pipeline.mjs").write_text("")
    return Settings(database_url="sqlite+aiosqlite://", environment="test", auth_test_mode=True, career_ops_code_root=code, career_ops_workspace_root=tmp_path / "users")


def profile(user_id):
    return CandidateProfile(user_id=user_id, master_cv="# Private CV", profile_yaml="candidate: {}\n", profile_markdown="# Private profile", custom_markdown="", brief_markdown="# Private brief", cv_facts={"allow_metrics": [], "allow_facts": [], "forbidden_phrases": [], "warn_phrases": []}, portals_yaml="title_filter:\n  positive: [Director]\n")


def test_workspace_is_uuid_scoped_and_materialized(tmp_path):
    config = settings(tmp_path)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    workspace_a = materialize_profile(user_a, profile(user_a), config)
    workspace_b = materialize_profile(user_b, profile(user_b), config)
    assert workspace_a != workspace_b
    assert workspace_a.name == str(user_a)
    assert workspace_b.name == str(user_b)
    assert (workspace_a / "cv.md").read_text() == "# Private CV"
    assert (workspace_a / "modes" / "oferta.md").is_symlink()
    assert candidate_environment(workspace_a)["CAREER_OPS_ROOT"] == str(workspace_a)


def test_workspace_rejects_non_uuid_scope(tmp_path):
    config = settings(tmp_path)
    with pytest.raises((AttributeError, ValueError)):
        workspace_for("../../other-user", config)


def test_production_cannot_enable_test_auth():
    with pytest.raises(ValueError):
        Settings(database_url="postgresql://example.invalid/db", environment="production", auth_test_mode=True, clerk_secret_key="secret")
