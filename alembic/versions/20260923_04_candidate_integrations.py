"""candidate integrations (gmail/linkedin alert ingestion)

Revision ID: 20260923_04
Revises: 20260922_03
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260923_04"
down_revision: Union[str, Sequence[str], None] = "20260922_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="disconnected"),
        sa.Column("account_email", sa.String(320)),
        sa.Column("scopes", sa.String(500)),
        sa.Column("encrypted_credentials", sa.Text()),
        sa.Column("sync_cursor", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_status", sa.String(20)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_candidate_integrations_user_provider"),
    )
    op.create_index("ix_candidate_integrations_user_id", "candidate_integrations", ["user_id"])
    op.create_index("ix_candidate_integrations_provider", "candidate_integrations", ["provider"])
    op.create_index("ix_candidate_integrations_status", "candidate_integrations", ["status"])

    op.create_table(
        "oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("state", sa.String(128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("state", name="uq_oauth_states_state"),
    )
    op.create_index("ix_oauth_states_state", "oauth_states", ["state"])
    op.create_index("ix_oauth_states_user_id", "oauth_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_states_user_id", table_name="oauth_states")
    op.drop_index("ix_oauth_states_state", table_name="oauth_states")
    op.drop_table("oauth_states")

    op.drop_index("ix_candidate_integrations_status", table_name="candidate_integrations")
    op.drop_index("ix_candidate_integrations_provider", table_name="candidate_integrations")
    op.drop_index("ix_candidate_integrations_user_id", table_name="candidate_integrations")
    op.drop_table("candidate_integrations")
