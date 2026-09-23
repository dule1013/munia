"""candidate_jobs: triaged_at marker (distinguish placeholder "uncertain" from a real triage decision)

Revision ID: 20260928_09
Revises: 20260927_08
Create Date: 2026-09-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260928_09"
down_revision: Union[str, Sequence[str], None] = "20260927_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("candidate_jobs", sa.Column("triaged_at", sa.DateTime(timezone=True)))
    op.create_index("ix_candidate_jobs_triaged_at", "candidate_jobs", ["triaged_at"])


def downgrade() -> None:
    op.drop_index("ix_candidate_jobs_triaged_at", table_name="candidate_jobs")
    op.drop_column("candidate_jobs", "triaged_at")
