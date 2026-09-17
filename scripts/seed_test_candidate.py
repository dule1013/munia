import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.modules.candidates.models import CandidateProfile, User
from app.modules.jobs.models import Job
from app.modules.pipeline.models import CandidateJob
from sqlalchemy import select


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clerk-user-id", default="test_candidate_phase4")
    parser.add_argument("--email", default="test-candidate@career-ops.local")
    args = parser.parse_args()
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.clerk_user_id == args.clerk_user_id))
        if user is None:
            user = User(clerk_user_id=args.clerk_user_id, email=args.email, name="Phase 4 Test Candidate")
            db.add(user)
            await db.flush()
            db.add(CandidateProfile(user_id=user.id, master_cv="# CV -- Phase 4 Test Candidate\n", profile={"target_roles": {"primary": ["Engineering Manager"]}}, profile_yaml="target_roles:\n  primary:\n    - Engineering Manager\n", profile_markdown="# Candidate profile\n", cv_facts={"allow_metrics": [], "allow_facts": [], "forbidden_phrases": [], "warn_phrases": []}, onboarding_complete=True))
        shared_job = await db.scalar(select(Job).order_by(Job.created_at))
        if shared_job:
            item = await db.scalar(select(CandidateJob).where(CandidateJob.user_id == user.id, CandidateJob.job_id == shared_job.id))
            if item is None:
                db.add(CandidateJob(user_id=user.id, job_id=shared_job.id, eligibility="uncertain", triage_result="uncertain", triage_reason="Fictional isolation-test state", pipeline_status="Skipped", skipped=True))
        await db.commit()
        print(f"Seeded test candidate {user.id}")


if __name__ == "__main__":
    asyncio.run(main())
