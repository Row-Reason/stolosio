"""Independent capture acquisition analytics.

Revision ID: 20261003_01
Revises: 20260930_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20261003_01"
down_revision = "20260930_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "capture_results",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acquisition_outcome", sa.String(32), nullable=False),
        *[
            sa.Column(name, sa.Boolean(), nullable=False)
            for name in (
                "resolution_enabled",
                "challenge_detected",
                "local_attempted",
                "external_attempted",
                "paid",
            )
        ],
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("local_seconds", sa.Float(), nullable=False),
        sa.Column("external_seconds", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "acquisition_outcome IN ('default', 'internally_resolved', "
            "'externally_resolved', 'total_failure')"
        ),
    )
    op.create_index("ix_capture_results_completed_at", "capture_results", ["completed_at"])


def downgrade():
    op.drop_table("capture_results")
