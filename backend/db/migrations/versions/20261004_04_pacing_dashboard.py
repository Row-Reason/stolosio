"""Persist compact pacing dashboard facts.

Revision ID: 20261004_04
Revises: 20261004_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20261004_04"
down_revision = "20261004_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "domain_pacing_state",
        sa.Column("reset_requested", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "domain_pacing_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hostname", sa.String(253), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("refusal", sa.String(32)),
        sa.Column("outcome", sa.String(16)),
        sa.Column("active_captures", sa.Integer(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("spacing_seconds", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_domain_pacing_requests_host_started",
        "domain_pacing_requests",
        ["hostname", "started_at"],
    )
    op.create_index("ix_domain_pacing_requests_started", "domain_pacing_requests", ["started_at"])


def downgrade() -> None:
    op.drop_table("domain_pacing_requests")
    op.drop_column("domain_pacing_state", "reset_requested")
