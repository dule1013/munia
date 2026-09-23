"""ats_scan_cursors: persistent deterministic reverse-ATS rotation

Revision ID: 20260926_07
Revises: 20260925_06
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260926_07"
down_revision: Union[str, Sequence[str], None] = "20260925_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ats_scan_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("next_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dataset_size", sa.Integer()),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(20)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", name="uq_ats_scan_cursors_source"),
    )
    op.create_index("ix_ats_scan_cursors_source", "ats_scan_cursors", ["source"])


def downgrade() -> None:
    op.drop_index("ix_ats_scan_cursors_source", table_name="ats_scan_cursors")
    op.drop_table("ats_scan_cursors")
