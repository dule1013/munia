import json
import os
import uuid
from pathlib import Path

from app.core.config import Settings
from app.modules.candidates.models import CandidateProfile

USER_ROOT_FILES = {"cv.md", "article-digest.md", "portals.yml", "voice-dna.md"}
USER_MODE_FILES = {"_profile.md", "_custom.md", "_brief.md"}
USER_CONFIG_FILES = {"profile.yml", "cv-facts.json", "benchmarks.yml", "plugins.yml"}


def workspace_for(user_id: uuid.UUID, settings: Settings) -> Path:
    root = settings.career_ops_workspace_root.resolve()
    workspace = (root / str(user_id)).resolve()
    if workspace.parent != root:
        raise ValueError("invalid candidate workspace")
    return workspace


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def link_if_missing(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        return
    target.symlink_to(source, target_is_directory=source.is_dir())


def ensure_system_layer(workspace: Path, settings: Settings) -> None:
    code = settings.career_ops_code_root.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    for directory in ("data", "reports", "output", "documents", "interview-prep", "writing-samples", "modes", "config", "batch/tracker-additions", "batch/logs"):
        (workspace / directory).mkdir(parents=True, exist_ok=True)
    for entry in code.iterdir():
        if entry.name.startswith(".") or entry.name in USER_ROOT_FILES or entry.name in {"data", "reports", "output", "documents", "interview-prep", "writing-samples", "modes", "config", "web", "app", "alembic", "tests", "node_modules"}:
            continue
        if entry.is_file() and (entry.suffix in {".mjs", ".json"} or entry.name in {"AGENTS.md", "CLAUDE.md", "CODEX.md", "package.json"}):
            link_if_missing(entry, workspace / entry.name)
        elif entry.is_dir() and entry.name in {"lib", "providers", "templates", "schemas", "plugins", ".agents"}:
            link_if_missing(entry, workspace / entry.name)
    for entry in (code / "modes").iterdir():
        if entry.name not in USER_MODE_FILES:
            link_if_missing(entry, workspace / "modes" / entry.name)
    for entry in (code / "config").iterdir():
        if entry.name not in USER_CONFIG_FILES:
            link_if_missing(entry, workspace / "config" / entry.name)


def materialize_profile(user_id: uuid.UUID, profile: CandidateProfile, settings: Settings) -> Path:
    workspace = workspace_for(user_id, settings)
    ensure_system_layer(workspace, settings)
    atomic_write(workspace / "cv.md", profile.master_cv)
    atomic_write(workspace / "config" / "profile.yml", profile.profile_yaml)
    atomic_write(workspace / "modes" / "_profile.md", profile.profile_markdown)
    atomic_write(workspace / "modes" / "_custom.md", profile.custom_markdown)
    atomic_write(workspace / "modes" / "_brief.md", profile.brief_markdown)
    atomic_write(workspace / "config" / "cv-facts.json", json.dumps(profile.cv_facts, indent=2, ensure_ascii=False) + "\n")
    atomic_write(workspace / "portals.yml", profile.portals_yaml)
    return workspace


def candidate_environment(workspace: Path) -> dict[str, str]:
    return {**os.environ, "CAREER_OPS_ROOT": str(workspace), "CAREER_OPS_DATA_DIR": str(workspace), "CAREER_OPS_TRACKER": str(workspace / "data" / "applications.md"), "CAREER_OPS_PORTALS": str(workspace / "portals.yml"), "CAREER_OPS_PDF_INDEX": str(workspace / "data" / "pdf-index.tsv")}
