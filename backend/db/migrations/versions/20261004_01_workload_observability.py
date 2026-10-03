"""Separate capture results from automation lifecycle state.

Revision ID: 20261004_01
Revises: 20261003_01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261004_01"
down_revision = "20261003_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_sessions",
        sa.Column("workload", sa.String(16), nullable=False, server_default="automation"),
    )
    op.add_column("gateway_sessions", sa.Column("capture_hostname", sa.String(253)))
    op.add_column("gateway_sessions", sa.Column("capture_summary", postgresql.JSONB()))
    # Retained records identify historical captures without guessing missing evidence.
    op.execute(
        "UPDATE gateway_sessions SET workload = 'capture' WHERE id IN "
        "(SELECT session_id FROM capture_results UNION SELECT session_id FROM "
        "session_events WHERE event_type = 'capture.completed')"
    )
    op.create_index("ix_gateway_sessions_workload", "gateway_sessions", ["workload"])


def downgrade() -> None:
    op.drop_index("ix_gateway_sessions_workload", table_name="gateway_sessions")
    op.drop_column("gateway_sessions", "capture_summary")
    op.drop_column("gateway_sessions", "capture_hostname")
    op.drop_column("gateway_sessions", "workload")
