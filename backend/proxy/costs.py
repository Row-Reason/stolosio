from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import AcquisitionAttempt, GatewaySession, ProviderCostRate
from backend.proxy.contracts import ProviderName


@dataclass(frozen=True, slots=True)
class CostWindow:
    key: str
    duration: timedelta
    bucket: str


COST_WINDOWS = {
    "24h": CostWindow("24h", timedelta(hours=24), "hour"),
    "7d": CostWindow("7d", timedelta(days=7), "day"),
    "30d": CostWindow("30d", timedelta(days=30), "day"),
    "90d": CostWindow("90d", timedelta(days=90), "day"),
}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CostQueryService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def overview(self, window_key: str) -> dict[str, object]:
        window = COST_WINDOWS.get(window_key)
        if window is None:
            raise ValueError("invalid cost window")
        ends_at = datetime.now(UTC)
        starts_at = ends_at - window.duration
        filters = (
            AcquisitionAttempt.finished_at.is_not(None),
            AcquisitionAttempt.finished_at >= starts_at,
            AcquisitionAttempt.finished_at <= ends_at,
        )

        async with self._sessions() as database:
            provider_rows = list(
                await database.execute(
                    select(
                        AcquisitionAttempt.provider,
                        func.count(AcquisitionAttempt.id),
                        func.count(distinct(AcquisitionAttempt.session_id)),
                        func.count(
                            case(
                                (AcquisitionAttempt.state == "failed", 1),
                            )
                        ),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.modeled_cost_units), 0
                        ),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.chargeable_time_ms), 0
                        ),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.browser_connected_ms), 0
                        ),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.capacity_occupied_ms), 0
                        ),
                    )
                    .where(*filters)
                    .group_by(AcquisitionAttempt.provider)
                    .order_by(AcquisitionAttempt.provider)
                )
            )
            bucket_start = func.date_trunc(
                window.bucket, AcquisitionAttempt.finished_at
            ).label("bucket_start")
            bucket_rows = list(
                await database.execute(
                    select(
                        bucket_start,
                        AcquisitionAttempt.provider,
                        func.count(AcquisitionAttempt.id),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.modeled_cost_units), 0
                        ),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.chargeable_time_ms), 0
                        ),
                    )
                    .where(*filters)
                    .group_by(bucket_start, AcquisitionAttempt.provider)
                    .order_by(bucket_start, AcquisitionAttempt.provider)
                )
            )
            session_count, finalized_through = (
                await database.execute(
                    select(
                        func.count(distinct(AcquisitionAttempt.session_id)),
                        func.max(AcquisitionAttempt.finished_at),
                    ).where(*filters)
                )
            ).one()
            recent_rows = list(
                await database.execute(
                    select(
                        AcquisitionAttempt.session_id,
                        GatewaySession.client_reference,
                        GatewaySession.closed_at,
                        func.array_agg(
                            distinct(AcquisitionAttempt.provider)
                        ).label("providers"),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.modeled_cost_units), 0
                        ).label("modeled_cost_units"),
                        func.coalesce(
                            func.sum(AcquisitionAttempt.chargeable_time_ms), 0
                        ).label("chargeable_time_ms"),
                    )
                    .join(
                        GatewaySession,
                        GatewaySession.id == AcquisitionAttempt.session_id,
                    )
                    .where(*filters)
                    .group_by(
                        AcquisitionAttempt.session_id,
                        GatewaySession.client_reference,
                        GatewaySession.closed_at,
                    )
                    .order_by(
                        func.sum(
                            AcquisitionAttempt.modeled_cost_units
                        ).desc().nullslast(),
                        GatewaySession.closed_at.desc().nullslast(),
                    )
                    .limit(10)
                )
            )

        providers = [
            {
                "provider": provider,
                "attempt_count": int(attempt_count),
                "session_count": int(provider_session_count),
                "failed_attempt_count": int(failed_attempt_count),
                "modeled_cost_units": int(modeled_cost_units),
                "chargeable_time_ms": int(chargeable_time_ms),
                "browser_connected_time_ms": int(browser_connected_time_ms),
                "capacity_occupied_time_ms": int(capacity_occupied_time_ms),
            }
            for (
                provider,
                attempt_count,
                provider_session_count,
                failed_attempt_count,
                modeled_cost_units,
                chargeable_time_ms,
                browser_connected_time_ms,
                capacity_occupied_time_ms,
            ) in provider_rows
        ]
        totals = {
            "session_count": int(session_count),
            "attempt_count": sum(int(row["attempt_count"]) for row in providers),
            "failed_attempt_count": sum(
                int(row["failed_attempt_count"]) for row in providers
            ),
            "modeled_cost_units": sum(
                int(row["modeled_cost_units"]) for row in providers
            ),
            "chargeable_time_ms": sum(
                int(row["chargeable_time_ms"]) for row in providers
            ),
            "browser_connected_time_ms": sum(
                int(row["browser_connected_time_ms"]) for row in providers
            ),
            "browserless_slot_time_ms": sum(
                int(row["capacity_occupied_time_ms"])
                for row in providers
                if row["provider"] == ProviderName.BROWSERLESS.value
            ),
        }
        return {
            "window": window.key,
            "starts_at": _iso(starts_at),
            "ends_at": _iso(ends_at),
            "finalized_through": _iso(finalized_through),
            "totals": totals,
            "providers": providers,
            "buckets": [
                {
                    "started_at": _iso(started_at),
                    "provider": provider,
                    "attempt_count": int(attempt_count),
                    "modeled_cost_units": int(modeled_cost_units),
                    "chargeable_time_ms": int(chargeable_time_ms),
                }
                for (
                    started_at,
                    provider,
                    attempt_count,
                    modeled_cost_units,
                    chargeable_time_ms,
                ) in bucket_rows
            ],
            "recent_sessions": [
                {
                    "session_id": session_id,
                    "client_reference": client_reference,
                    "closed_at": _iso(closed_at),
                    "providers": sorted(providers),
                    "modeled_cost_units": int(modeled_cost_units),
                    "chargeable_time_ms": int(chargeable_time_ms),
                }
                for (
                    session_id,
                    client_reference,
                    closed_at,
                    providers,
                    modeled_cost_units,
                    chargeable_time_ms,
                ) in recent_rows
            ],
        }


_DEFAULT_COST_RATES = {
    ProviderName.BROWSERLESS: 100,
    ProviderName.BROWSERLESS_CLOUD: 300,
}


class CostRateRepository:
    """Operator-set cost units per second of chargeable time, applied when attempts finish."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def ensure_defaults(self) -> None:
        async with self._sessions.begin() as database:
            await database.execute(
                insert(ProviderCostRate)
                .values(
                    [
                        {
                            "provider": provider.value,
                            "cost_units_per_second": cost,
                            "updated_at": datetime.now(UTC),
                        }
                        for provider, cost in _DEFAULT_COST_RATES.items()
                    ]
                )
                .on_conflict_do_nothing(index_elements=[ProviderCostRate.provider])
            )

    async def list(self) -> list[ProviderCostRate]:
        async with self._sessions() as database:
            return list(
                await database.scalars(select(ProviderCostRate).order_by(ProviderCostRate.provider))
            )

    async def update(
        self,
        provider: ProviderName,
        cost_units_per_second: int,
    ) -> ProviderCostRate | None:
        if cost_units_per_second < 0:
            raise ValueError("Cost rates must be non-negative")
        async with self._sessions.begin() as database:
            row = await database.get(ProviderCostRate, provider.value, with_for_update=True)
            if row is None:
                return None
            row.cost_units_per_second = cost_units_per_second
            row.updated_at = datetime.now(UTC)
            return row
