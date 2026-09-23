"""candidate ai configs (per-candidate encrypted AI provider key)

Revision ID: 20260924_05
Revises: 20260923_04
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260924_05"
down_revision: Union[str, Sequence[str], None] = "20260923_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_ai_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("last_manual_search_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_candidate_ai_configs_user_provider"),
    )
    op.create_index("ix_candidate_ai_configs_user_id", "candidate_ai_configs", ["user_id"])
    op.create_index("ix_candidate_ai_configs_provider", "candidate_ai_configs", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_candidate_ai_configs_provider", table_name="candidate_ai_configs")
    op.drop_index("ix_candidate_ai_configs_user_id", table_name="candidate_ai_configs")
    op.drop_table("candidate_ai_configs")
