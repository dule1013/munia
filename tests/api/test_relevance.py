import uuid

from app.modules.automation.batch import relevant_to_candidate
from app.modules.candidates.models import CandidateProfile
from app.modules.jobs.models import Job


def test_candidate_relevance_is_private_interpretation_of_shared_job():
    job = Job(id=uuid.uuid4(), canonical_key="x", canonical_url="https://example.com/1", company="Acme", title="Director of Engineering", location="Madrid, Spain", source="test", posting_url="https://example.com/1", source_metadata={})
    director = CandidateProfile(user_id=uuid.uuid4(), profile={"target_roles": {"primary": ["Director of Engineering"]}, "authorization": {"work_authorization": ["Spain"]}})
    designer = CandidateProfile(user_id=uuid.uuid4(), profile={"target_roles": {"primary": ["Design Director"]}, "authorization": {"work_authorization": ["Spain"]}})
    assert relevant_to_candidate(job, director)
    assert not relevant_to_candidate(job, designer)
