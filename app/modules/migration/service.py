import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.artifacts.models import TailoredCv
from app.modules.automation.workspace import workspace_for
from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import upsert_job
from app.modules.migration.parsers import first_url, markdown_table, pdf_index_rows, pipeline_rows, report_number, score_value, tsv_rows
from app.modules.pipeline.models import CandidateJob, Evaluation

PRESERVED_PATHS = ["cv.md", "article-digest.md", "voice-dna.md", "portals.yml", "config/profile.yml", "config/cv-facts.json", "config/benchmarks.yml", "modes/_profile.md", "modes/_custom.md", "modes/_brief.md", "data", "reports", "output", "documents", "interview-prep", "writing-samples"]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def copy_legacy_data(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in PRESERVED_PATHS:
        src = source / relative
        if not src.exists():
            continue
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def backup_legacy_data(source: Path, settings: Settings) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = settings.career_ops_workspace_root.parent / "backups" / f"pre-phase4-{stamp}"
    copy_legacy_data(source, backup)
    return backup


def load_json(path: Path) -> dict:
    content = read_text(path)
    if not content:
        return {}
    value = json.loads(content)
    return value if isinstance(value, dict) else {}


def profile_identity(source: Path) -> tuple[str, str, dict]:
    value = yaml.safe_load(read_text(source / "config/profile.yml")) or {}
    candidate = value.get("candidate") or {}
    return str(candidate.get("full_name") or "Migrated candidate"), str(candidate.get("email") or "migrated@invalid.local"), value


async def migrated_user(db: AsyncSession, clerk_user_id: str, name: str, email: str) -> User:
    user = await db.scalar(select(User).where((User.clerk_user_id == clerk_user_id) | (User.email == email)))
    if user:
        return user
    user = User(clerk_user_id=clerk_user_id, name=name, email=email)
    db.add(user)
    await db.flush()
    return user


async def import_candidate_profile(db: AsyncSession, user: User, source: Path, structured: dict) -> CandidateProfile:
    profile = await db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    values = {
        "profile": structured,
        "master_cv": read_text(source / "cv.md"),
        "profile_yaml": read_text(source / "config/profile.yml"),
        "profile_markdown": read_text(source / "modes/_profile.md"),
        "custom_markdown": read_text(source / "modes/_custom.md"),
        "brief_markdown": read_text(source / "modes/_brief.md"),
        "cv_facts": load_json(source / "config/cv-facts.json"),
        "portals_yaml": read_text(source / "portals.yml"),
        "onboarding_complete": True,
    }
    if profile is None:
        profile = CandidateProfile(user_id=user.id, **values)
        db.add(profile)
    else:
        for key, value in values.items():
            setattr(profile, key, value)
    await db.flush()
    return profile


async def candidate_job(db: AsyncSession, user_id: uuid.UUID, job: Job) -> CandidateJob:
    item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user_id, CandidateJob.job_id == job.id))
    if item is None:
        item = CandidateJob(user_id=user_id, job_id=job.id)
        db.add(item)
        await db.flush()
    return item


async def import_pipeline(db: AsyncSession, user: User, source: Path) -> dict[str, Job]:
    jobs: dict[str, Job] = {}
    for row in pipeline_rows(read_text(source / "data/pipeline.md")):
        payload = JobIngest(company=row.company, title=row.title, location=row.location, source=row.labels.get("source", "legacy-pipeline"), posting_url=row.url, direct_application_url=row.url, is_active=row.labels.get("liveness", "active") != "expired")
        job, _ = await upsert_job(db, payload)
        item = await candidate_job(db, user.id, job)
        item.pipeline_status = "Processed" if row.done else "Inbox"
        item.eligibility = row.labels.get("eligibility")
        item.triage_reason = row.labels.get("reason") or row.labels.get("note")
        jobs[row.url] = job
    return jobs


async def import_scan_history(db: AsyncSession, source: Path, known: dict[str, Job]) -> None:
    for row in tsv_rows(read_text(source / "data/scan-history.tsv")):
        url = row.get("url") or row.get("URL") or ""
        company = row.get("company") or row.get("Company") or "Unknown"
        title = row.get("title") or row.get("role") or row.get("Title") or "Unknown role"
        if not url.startswith(("http://", "https://")) or url in known:
            continue
        payload = JobIngest(company=company, title=title, location=row.get("location", ""), source=row.get("source", "legacy-scan"), posting_url=url, direct_application_url=url)
        job, _ = await upsert_job(db, payload)
        known[url] = job


async def import_applications(db: AsyncSession, user: User, source: Path, known: dict[str, Job]) -> dict[int, tuple[CandidateJob, Evaluation]]:
    imported: dict[int, tuple[CandidateJob, Evaluation]] = {}
    for row in markdown_table(read_text(source / "data/applications.md")):
        company = row.get("company", "Unknown")
        title = row.get("role") or row.get("title") or "Unknown role"
        report_no = report_number(row.get("report", ""))
        report_path = next(iter(sorted((source / "reports").glob(f"{report_no:03d}-*.md"))), None) if report_no is not None else None
        report = read_text(report_path) if report_path else ""
        url = first_url(row.get("notes", ""), report) or f"https://legacy.invalid/application/{row.get('#') or row.get('n') or uuid.uuid4()}"
        job = known.get(url)
        if job is None:
            job, _ = await upsert_job(db, JobIngest(company=company, title=title, source="legacy-tracker", posting_url=url, direct_application_url=url, is_active=True))
            known[url] = job
        item = await candidate_job(db, user.id, job)
        item.pipeline_status = row.get("status", "Evaluated") or "Evaluated"
        item.fit_score = score_value(row.get("score", ""))
        evaluation = await db.scalar(select(Evaluation).where(Evaluation.candidate_job_id == item.id, Evaluation.report_number == report_no))
        if evaluation is None:
            evaluation = Evaluation(candidate_job_id=item.id, report_number=report_no, score=item.fit_score, recommendation=row.get("recommendation"), report_markdown=report)
            db.add(evaluation)
            await db.flush()
        if report_no is not None:
            imported[report_no] = (item, evaluation)
    return imported


async def import_tailored_cvs(db: AsyncSession, user: User, source: Path, evaluations: dict[int, tuple[CandidateJob, Evaluation]]) -> None:
    for row in pdf_index_rows(read_text(source / "data/pdf-index.tsv")):
        number = report_number(row.get("report", ""))
        linked = evaluations.get(number) if number is not None else None
        if not linked:
            continue
        item, evaluation = linked
        html_relative = row.get("html", "")
        pdf_relative = row.get("pdf", "")
        html = read_text(source / html_relative) if html_relative else ""
        if not html:
            continue
        cv = await db.scalar(select(TailoredCv).where(TailoredCv.user_id == user.id, TailoredCv.job_id == item.job_id))
        values = {"evaluation_id": evaluation.id, "source_html": html, "artifact_key": pdf_relative or None, "format": row.get("format", "a4"), "manually_edited": bool(html_relative and (source / f"{html_relative}.manual-edit.json").exists()), "validation_status": "valid"}
        if cv is None:
            db.add(TailoredCv(user_id=user.id, job_id=item.job_id, **values))
        else:
            for key, value in values.items():
                setattr(cv, key, value)


async def migrate_legacy_candidate(db: AsyncSession, source: Path, settings: Settings, clerk_user_id: str) -> tuple[User, Path]:
    source = source.resolve()
    backup = backup_legacy_data(source, settings)
    name, email, structured = profile_identity(source)
    user = await migrated_user(db, clerk_user_id, name, email)
    await import_candidate_profile(db, user, source, structured)
    workspace = workspace_for(user.id, settings)
    copy_legacy_data(source, workspace)
    known = await import_pipeline(db, user, source)
    await import_scan_history(db, source, known)
    evaluations = await import_applications(db, user, source, known)
    await import_tailored_cvs(db, user, source, evaluations)
    await db.commit()
    return user, backup
