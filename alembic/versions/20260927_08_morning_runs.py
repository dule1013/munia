"""morning_runs: minimal run correlation for Today's "N new" count

Revision ID: 20260927_08
Revises: 20260926_07
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260927_08"
down_revision: Union[str, Sequence[str], None] = "20260926_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "morning_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_morning_runs_status", "morning_runs", ["status"])

    op.add_column("candidate_jobs", sa.Column("ai_fit_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("morning_runs.id", ondelete="SET NULL")))
    op.create_index("ix_candidate_jobs_ai_fit_run_id", "candidate_jobs", ["ai_fit_run_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_jobs_ai_fit_run_id", table_name="candidate_jobs")
    op.drop_column("candidate_jobs", "ai_fit_run_id")
    op.drop_index("ix_morning_runs_status", table_name="morning_runs")
    op.drop_table("morning_runs")
