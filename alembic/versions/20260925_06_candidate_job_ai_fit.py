"""candidate_jobs: lightweight morning AI fit assessment columns

Revision ID: 20260925_06
Revises: 20260924_05
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260925_06"
down_revision: Union[str, Sequence[str], None] = "20260924_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("candidate_jobs", sa.Column("ai_fit", sa.String(20)))
    op.add_column("candidate_jobs", sa.Column("ai_fit_reason", sa.Text()))
    op.add_column("candidate_jobs", sa.Column("ai_fit_confidence", sa.String(10)))
    op.add_column("candidate_jobs", sa.Column("ai_fit_assessed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_candidate_jobs_ai_fit", "candidate_jobs", ["ai_fit"])
    op.create_index("ix_candidate_jobs_ai_fit_assessed_at", "candidate_jobs", ["ai_fit_assessed_at"])


def downgrade() -> None:
    op.drop_index("ix_candidate_jobs_ai_fit_assessed_at", table_name="candidate_jobs")
    op.drop_index("ix_candidate_jobs_ai_fit", table_name="candidate_jobs")
    op.drop_column("candidate_jobs", "ai_fit_assessed_at")
    op.drop_column("candidate_jobs", "ai_fit_confidence")
    op.drop_column("candidate_jobs", "ai_fit_reason")
    op.drop_column("candidate_jobs", "ai_fit")
