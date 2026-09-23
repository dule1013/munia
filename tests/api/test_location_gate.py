"""apply_location_eligibility wires the deterministic classifier into the
real per-candidate pipeline (Phase 5 follow-up §3) — not just a tested-in-
isolation helper."""

import uuid

from sqlalchemy import select

from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.schemas import JobIngest
from app.modules.jobs.service import ingest_discovery
from app.modules.pipeline.models import CandidateJob
from app.modules.pipeline.service import apply_location_eligibility, has_candidate_decision


DUSAN_PROFILE = {"location": {"city": "Madrid", "country": "Spain", "authorized_in": ["Spain", "European Union", "European Economic Area"]}}


async def seed_user_with_profile(sessions, profile: dict, clerk_user_id: str = "clerk-a") -> User:
    async with sessions() as db:
        user = User(id=uuid.uuid4(), clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", name=clerk_user_id)
        db.add(user)
        await db.flush()
        db.add(CandidateProfile(user_id=user.id, profile=profile))
        await db.commit()
        return user


async def seed_candidate_job(sessions, user, *, title: str, location: str, description: str = ""):
    async with sessions() as db:
        payload = JobIngest(company="Acme", title=title, location=location, description=description, source="greenhouse", posting_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}", direct_application_url=f"https://job-boards.greenhouse.io/acme/{uuid.uuid4()}")
        job, _, _ = await ingest_discovery(db, payload, method="reverse_ats")
        item = CandidateJob(user_id=user.id, job_id=job.id, triage_result="uncertain")
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item.id


async def test_ineligible_job_is_hard_discarded_and_excluded_from_inbox(api):
    from app.modules.pipeline.service import list_inbox

    _, sessions, _ = api
    user = await seed_user_with_profile(sessions, DUSAN_PROFILE)
    cj_id = await seed_candidate_job(sessions, user, title="Director of Engineering", location="US Remote")

    async with sessions() as db:
        classified = await apply_location_eligibility(db, user.id)
    assert classified == 1

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        assert item.eligibility == "ineligible"
        assert item.triage_result == "discard"
        inbox = await list_inbox(db, user.id)
    assert inbox == []


async def test_eligible_job_keeps_uncertain_triage_for_further_processing(api):
    _, sessions, _ = api
    user = await seed_user_with_profile(sessions, DUSAN_PROFILE)
    cj_id = await seed_candidate_job(sessions, user, title="Director of Engineering", location="Madrid, Spain")

    async with sessions() as db:
        await apply_location_eligibility(db, user.id)

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        assert item.eligibility == "eligible"
        assert item.triage_result == "uncertain"  # untouched — proceeds to triage/assessment


async def test_plausible_job_can_proceed(api):
    _, sessions, _ = api
    user = await seed_user_with_profile(sessions, DUSAN_PROFILE)
    cj_id = await seed_candidate_job(sessions, user, title="Director of Engineering", location="Remote - Europe")

    async with sessions() as db:
        await apply_location_eligibility(db, user.id)

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        assert item.eligibility == "plausible"
        assert item.triage_result == "uncertain"


async def test_never_overwrites_a_candidate_job_the_human_already_decided(api):
    _, sessions, _ = api
    user = await seed_user_with_profile(sessions, DUSAN_PROFILE)
    cj_id = await seed_candidate_job(sessions, user, title="Director of Engineering", location="US Remote")

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        item.pipeline_status = "Applied"  # human already acted
        await db.commit()
        await apply_location_eligibility(db, user.id)

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        assert item.eligibility is None  # untouched
        assert item.pipeline_status == "Applied"


async def test_already_classified_jobs_are_not_reclassified(api):
    _, sessions, _ = api
    user = await seed_user_with_profile(sessions, DUSAN_PROFILE)
    cj_id = await seed_candidate_job(sessions, user, title="Director of Engineering", location="US Remote")

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        item.eligibility = "plausible"  # e.g. set by some other path already
        await db.commit()
        classified = await apply_location_eligibility(db, user.id)
    assert classified == 0

    async with sessions() as db:
        item = await db.get(CandidateJob, cj_id)
        assert item.eligibility == "plausible"  # untouched, not re-run to "ineligible"


async def test_uses_the_richer_profile_location_block_matching_production_shape(api):
    """Exercises the exact shape verified against Dusan's real production
    CandidateProfile (location.country/city/authorized_in)."""
    _, sessions, _ = api
    user = await seed_user_with_profile(sessions, DUSAN_PROFILE)
    await seed_candidate_job(sessions, user, title="Director of Engineering", location="Madrid")

    async with sessions() as db:
        await apply_location_eligibility(db, user.id)
        item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id))
    assert item.eligibility == "eligible"
