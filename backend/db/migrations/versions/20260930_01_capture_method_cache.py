"""add the capture method cache

Revision ID: 20260930_01
Revises: 20260731_01
Create Date: 2026-09-30 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260930_01"
down_revision: str | None = "20260731_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capture_method_cache",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("entry", postgresql.JSONB(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_capture_method_cache_last_seen", "capture_method_cache", ["last_seen"])


def downgrade() -> None:
    op.drop_index("ix_capture_method_cache_last_seen", table_name="capture_method_cache")
    op.drop_table("capture_method_cache")
