"""discovery runs

Revision ID: 20260921_02
Revises: 20260915_01
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260921_02"
down_revision: Union[str, Sequence[str], None] = "20260915_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("discovery_runs", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("request", postgresql.JSONB(), nullable=False), sa.Column("result", postgresql.JSONB()), sa.Column("error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_index("ix_discovery_runs_user_id", "discovery_runs", ["user_id"])
    op.create_index("ix_discovery_runs_status", "discovery_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_discovery_runs_status", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_user_id", table_name="discovery_runs")
    op.drop_table("discovery_runs")
