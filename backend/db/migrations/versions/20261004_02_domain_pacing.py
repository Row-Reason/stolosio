"""Shared capture domain pacing.

Revision ID: 20261004_02
Revises: 20261004_01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261004_02"
down_revision = "20261004_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domain_pacing_settings",
        sa.Column("key", sa.String(16), primary_key=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "domain_pacing_state",
        sa.Column("hostname", sa.String(253), primary_key=True),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("spacing_seconds", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("next_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True)),
        sa.Column("healthy_samples", sa.Integer(), nullable=False),
        sa.Column("concurrency_samples", sa.Integer(), nullable=False),
        sa.Column("overload_samples", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("settings_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("adjusted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("concurrency >= 1 AND spacing_seconds > 0"),
    )
    op.create_index("ix_domain_pacing_state_expires_at", "domain_pacing_state", ["expires_at"])
    op.create_table(
        "domain_pacing_leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "hostname",
            sa.String(253),
            sa.ForeignKey("domain_pacing_state.hostname", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("gateway_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("at_limit", sa.Boolean(), nullable=False),
        sa.Column("concurrency_at_limit", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_domain_pacing_leases_host_expiry", "domain_pacing_leases", ["hostname", "expires_at"]
    )


def downgrade() -> None:
    op.drop_table("domain_pacing_leases")
    op.drop_table("domain_pacing_state")
    op.drop_table("domain_pacing_settings")
