"""job discoveries + company watchlist

Revision ID: 20260922_03
Revises: 20260921_02
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260922_03"
down_revision: Union[str, Sequence[str], None] = "20260921_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_discoveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id", "source", "method", "source_url", name="uq_job_discoveries_job_source_method_url"),
    )
    op.create_index("ix_job_discoveries_job_id", "job_discoveries", ["job_id"])
    op.create_index("ix_job_discoveries_user_id", "job_discoveries", ["user_id"])
    op.create_index("ix_job_discoveries_source", "job_discoveries", ["source"])
    op.create_index("ix_job_discoveries_method", "job_discoveries", ["method"])

    op.create_table(
        "watched_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("company_key", sa.String(255), nullable=False),
        sa.Column("careers_url", sa.Text()),
        sa.Column("provider", sa.String(100)),
        sa.Column("provider_tenant_id", sa.String(255)),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True)),
        sa.Column("scan_status", sa.String(30)),
        sa.Column("last_scan_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "company_key", name="uq_watched_companies_user_company"),
    )
    op.create_index("ix_watched_companies_user_id", "watched_companies", ["user_id"])
    op.create_index("ix_watched_companies_company_key", "watched_companies", ["company_key"])
    op.create_index("ix_watched_companies_enabled", "watched_companies", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_watched_companies_enabled", table_name="watched_companies")
    op.drop_index("ix_watched_companies_company_key", table_name="watched_companies")
    op.drop_index("ix_watched_companies_user_id", table_name="watched_companies")
    op.drop_table("watched_companies")

    op.drop_index("ix_job_discoveries_method", table_name="job_discoveries")
    op.drop_index("ix_job_discoveries_source", table_name="job_discoveries")
    op.drop_index("ix_job_discoveries_user_id", table_name="job_discoveries")
    op.drop_index("ix_job_discoveries_job_id", table_name="job_discoveries")
    op.drop_table("job_discoveries")
