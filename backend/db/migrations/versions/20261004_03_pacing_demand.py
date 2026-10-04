"""Record unmet spacing demand independently of client retry timing.

Revision ID: 20261004_03
Revises: 20261004_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20261004_03"
down_revision = "20261004_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "domain_pacing_state", sa.Column("spacing_refused_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("domain_pacing_state", "spacing_refused_at")
