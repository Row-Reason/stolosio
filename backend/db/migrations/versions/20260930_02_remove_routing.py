"""remove automatic routing, health probing and the HTTP and Browserbase providers

Clients name a provider (browserless by default) and capture decides its own method, so the
learned routing state, probes and routing profiles go. Their cost rates move to
provider_cost_rates. History recorded by the removed providers is deleted with its sessions.

Revision ID: 20260930_02
Revises: 20260930_01
Create Date: 2026-09-30 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_02"
down_revision: str | None = "20260930_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REMOVED = "('http', 'browserbase')"


def upgrade() -> None:
    op.drop_table("health_probes")
    op.drop_table("domain_provider_health")
    op.drop_table("domain_routing_preferences")
    op.drop_table("domain_provider_transition_stats")
    op.drop_table("routing_configuration")

    op.rename_table("provider_routing_profiles", "provider_cost_rates")
    op.drop_column("provider_cost_rates", "automatic_enabled")
    op.drop_column("provider_cost_rates", "provider_contract_version")

    op.drop_index(op.f("ix_gateway_sessions_health_evaluated_at"), table_name="gateway_sessions")
    op.drop_column("gateway_sessions", "health_evaluated_at")
    for column in (
        "selection_reason",
        "plan_version",
        "plan_position",
        "transition_trigger",
        "estimated_cost_units",
        "estimated_billable_ms",
    ):
        op.drop_column("acquisition_attempts", column)

    op.execute(
        "DELETE FROM gateway_sessions WHERE id IN "
        f"(SELECT session_id FROM acquisition_attempts WHERE provider IN {_REMOVED})"
    )
    for table in (
        "provider_cost_rates",
        "provider_command_cost_stats",
        "domain_provider_cost_stats",
        "external_provider_limits",
        "provider_fleets",
        "gateway_provider_state",
    ):
        op.execute(sa.text(f"DELETE FROM {table} WHERE provider IN {_REMOVED}"))


def downgrade() -> None:
    raise NotImplementedError("Automatic routing and the removed providers are not restorable")
