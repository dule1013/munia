"""multi user foundation

Revision ID: 20260915_01
Revises:
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260915_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("users", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("clerk_user_id", sa.String(255), nullable=False), sa.Column("email", sa.String(320), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("clerk_user_id"), sa.UniqueConstraint("email"))
    op.create_index("ix_users_clerk_user_id", "users", ["clerk_user_id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table("candidate_profiles", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("profile", postgresql.JSONB(), nullable=False), sa.Column("master_cv", sa.Text(), nullable=False), sa.Column("profile_yaml", sa.Text(), nullable=False), sa.Column("profile_markdown", sa.Text(), nullable=False), sa.Column("custom_markdown", sa.Text(), nullable=False), sa.Column("brief_markdown", sa.Text(), nullable=False), sa.Column("cv_facts", postgresql.JSONB(), nullable=False), sa.Column("portals_yaml", sa.Text(), nullable=False), sa.Column("onboarding_complete", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("user_id"))
    op.create_index("ix_candidate_profiles_user_id", "candidate_profiles", ["user_id"])
    op.create_table("jobs", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("canonical_key", sa.String(512), nullable=False), sa.Column("canonical_url", sa.Text(), nullable=False), sa.Column("company", sa.String(255), nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("location", sa.String(500), nullable=False), sa.Column("description", sa.Text()), sa.Column("source", sa.String(100), nullable=False), sa.Column("external_source_id", sa.String(255)), sa.Column("posting_url", sa.Text(), nullable=False), sa.Column("direct_application_url", sa.Text()), sa.Column("posted_at", sa.DateTime(timezone=True)), sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("source_metadata", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("canonical_url", name="uq_jobs_canonical_url"), sa.UniqueConstraint("canonical_key", name="uq_jobs_canonical_key"))
    op.create_index("ix_jobs_company", "jobs", ["company"])
    op.create_index("ix_jobs_title", "jobs", ["title"])
    op.create_index("ix_jobs_external_source_id", "jobs", ["external_source_id"])
    op.create_index("ix_jobs_posted_at", "jobs", ["posted_at"])
    op.create_index("ix_jobs_is_active", "jobs", ["is_active"])
    op.create_table("candidate_jobs", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("eligibility", sa.String(100)), sa.Column("triage_result", sa.String(30)), sa.Column("triage_reason", sa.Text()), sa.Column("triage_metadata", postgresql.JSONB(), nullable=False), sa.Column("fit_score", sa.Numeric(3, 2)), sa.Column("recommendation", sa.String(100)), sa.Column("pipeline_status", sa.String(50), nullable=False), sa.Column("saved", sa.Boolean(), nullable=False), sa.Column("skipped", sa.Boolean(), nullable=False), sa.Column("notes", sa.Text(), nullable=False), sa.Column("evaluated_at", sa.DateTime(timezone=True)), sa.Column("applied_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("user_id", "job_id", name="uq_candidate_jobs_user_job"))
    op.create_index("ix_candidate_jobs_user_id", "candidate_jobs", ["user_id"])
    op.create_index("ix_candidate_jobs_job_id", "candidate_jobs", ["job_id"])
    op.create_index("ix_candidate_jobs_triage_result", "candidate_jobs", ["triage_result"])
    op.create_index("ix_candidate_jobs_pipeline_status", "candidate_jobs", ["pipeline_status"])
    op.create_table("evaluations", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("candidate_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("candidate_jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("report_number", sa.Integer()), sa.Column("score", sa.Numeric(3, 2)), sa.Column("recommendation", sa.String(100)), sa.Column("report_markdown", sa.Text(), nullable=False), sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_evaluations_candidate_job_id", "evaluations", ["candidate_job_id"])
    op.create_index("ix_evaluations_report_number", "evaluations", ["report_number"])
    op.create_table("tailored_cvs", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluations.id", ondelete="SET NULL")), sa.Column("source_html", sa.Text(), nullable=False), sa.Column("artifact_key", sa.String(1000)), sa.Column("format", sa.String(20), nullable=False), sa.Column("manually_edited", sa.Boolean(), nullable=False), sa.Column("validation_status", sa.String(30), nullable=False), sa.Column("validation_message", sa.Text()), sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("modified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("user_id", "job_id", name="uq_tailored_cvs_user_job"))
    op.create_index("ix_tailored_cvs_user_id", "tailored_cvs", ["user_id"])
    op.create_index("ix_tailored_cvs_job_id", "tailored_cvs", ["job_id"])
    op.create_index("ix_tailored_cvs_evaluation_id", "tailored_cvs", ["evaluation_id"])


def downgrade() -> None:
    op.drop_table("tailored_cvs")
    op.drop_table("evaluations")
    op.drop_table("candidate_jobs")
    op.drop_table("jobs")
    op.drop_table("candidate_profiles")
    op.drop_table("users")
