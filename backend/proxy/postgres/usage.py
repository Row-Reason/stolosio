from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AcquisitionAttempt, ProviderCostRate


async def finalize_attempt_usage(
    database: AsyncSession,
    row: AcquisitionAttempt,
    now: datetime,
) -> None:
    if row.provider_started_at is not None and row.provider_ended_at is None:
        row.provider_ended_at = now
        row.provider_reported_ms = max(
            0,
            round((now - row.provider_started_at).total_seconds() * 1000),
        )
    if row.acquiring_at is not None:
        row.capacity_occupied_ms = max(
            0,
            round((now - row.acquiring_at).total_seconds() * 1000),
        )
    if row.active_at is not None:
        row.browser_connected_ms = max(
            0,
            round((now - row.active_at).total_seconds() * 1000),
        )
    # Every provider holds a browser slot from acquisition to release.
    row.chargeable_time_ms = row.capacity_occupied_ms
    row.cost_basis = "capacity_occupied"

    rate = await database.get(ProviderCostRate, row.provider)
    if rate is not None and row.chargeable_time_ms is not None:
        row.cost_rate_units_per_second = rate.cost_units_per_second
        row.modeled_cost_units = (
            row.chargeable_time_ms * rate.cost_units_per_second + 999
        ) // 1000
