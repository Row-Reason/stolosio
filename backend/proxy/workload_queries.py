"""Time-windowed, PostgreSQL-backed facts for both operator workloads."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Float, cast, func, select, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import AcquisitionAttempt, GatewaySession, SessionEventRecord
from backend.proxy.session_queries import _iso
from backend.proxy.workload_facts import (
    WINDOWS,
    capture_outcome_expression,
    capture_path_expression,
)


class WorkloadQueryService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def overview(self, window: str) -> dict:
        now = datetime.now(UTC)
        start = now - WINDOWS[window]
        output = {"window": window, "starts_at": _iso(start), "ends_at": _iso(now)}
        async with self._sessions() as database:
            # Counts, denominators and usage must describe one database snapshot.
            await database.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            for workload in ("automation", "capture"):
                completed = (
                    GatewaySession.workload == workload,
                    GatewaySession.closed_at >= start,
                    GatewaySession.closed_at <= now,
                )
                outcome = (
                    capture_outcome_expression() if workload == "capture" else GatewaySession.state
                )
                duration = (
                    cast(GatewaySession.capture_summary["duration_ms"].as_string(), Float)
                    if workload == "capture"
                    else func.extract("epoch", GatewaySession.closed_at - GatewaySession.created_at)
                    * 1000
                )
                counts = dict(
                    (
                        await database.execute(
                            select(outcome, func.count()).where(*completed).group_by(outcome)
                        )
                    ).all()
                )
                active = await database.scalar(
                    select(func.count())
                    .select_from(GatewaySession)
                    .where(
                        GatewaySession.workload == workload,
                        GatewaySession.state.in_(("admitted", "open", "closing")),
                        GatewaySession.lease_expires_at > now,
                    )
                )
                p50, p95 = (
                    await database.execute(
                        select(
                            func.percentile_cont(0.5).within_group(duration),
                            func.percentile_cont(0.95).within_group(duration),
                        ).where(*completed)
                    )
                ).one()
                usage = (
                    await database.execute(
                        select(
                            func.coalesce(func.sum(AcquisitionAttempt.capacity_occupied_ms), 0),
                            func.coalesce(func.sum(AcquisitionAttempt.browser_connected_ms), 0),
                            func.coalesce(func.sum(AcquisitionAttempt.modeled_cost_units), 0),
                        )
                        .join(GatewaySession, GatewaySession.id == AcquisitionAttempt.session_id)
                        .where(*completed)
                    )
                ).one()
                bucket = func.date_trunc(
                    "hour" if window == "24h" else "day", GatewaySession.closed_at, "UTC"
                )
                series_rows = (
                    await database.execute(
                        select(bucket, outcome, func.count())
                        .where(*completed)
                        .group_by(bucket, outcome)
                        .order_by(bucket)
                    )
                ).all()
                series = {}
                step = timedelta(hours=1) if window == "24h" else timedelta(days=1)
                cursor = start.replace(minute=0, second=0, microsecond=0)
                if window != "24h":
                    cursor = cursor.replace(hour=0)
                while cursor <= now:
                    series[_iso(cursor)] = {
                        "at": _iso(cursor),
                        "success": 0,
                        "failed": 0,
                        "other": 0,
                    }
                    cursor += step
                for at, status, count in series_rows:
                    key = (
                        "success"
                        if status in ("closed", "captured")
                        else ("failed" if status == "failed" else "other")
                    )
                    series[_iso(at)][key] += count
                failure_reason = (
                    func.coalesce(
                        GatewaySession.capture_summary["failure_code"].as_string(),
                        GatewaySession.terminal_reason,
                        "unknown",
                    )
                    if workload == "capture"
                    else func.coalesce(GatewaySession.terminal_reason, "unknown")
                )
                failure_rows = (
                    await database.execute(
                        select(failure_reason, func.count())
                        .where(*completed, outcome.not_in(("closed", "captured")))
                        .group_by(failure_reason)
                        .order_by(func.count().desc())
                        .limit(5)
                    )
                ).all()
                value = {
                    "active": int(active or 0),
                    "counts": counts,
                    "median_duration_ms": p50,
                    "p95_duration_ms": p95,
                    "capacity_ms": int(usage[0]),
                    "browser_ms": int(usage[1]),
                    "modeled_cost_units": int(usage[2]),
                    "series": list(series.values()),
                    "failures": [
                        {"reason": reason, "count": count} for reason, count in failure_rows
                    ],
                }
                if workload == "capture":
                    path = capture_path_expression()
                    paths = (
                        await database.execute(
                            select(path, func.count())
                            .where(*completed, outcome == "captured")
                            .group_by(path)
                        )
                    ).all()
                    browser_seconds, paid = (
                        await database.execute(
                            select(
                                func.coalesce(
                                    func.sum(
                                        cast(
                                            GatewaySession.capture_summary[
                                                "browser_seconds"
                                            ].as_string(),
                                            Float,
                                        )
                                    ),
                                    0,
                                ),
                                func.count().filter(
                                    GatewaySession.capture_summary["paid"].as_boolean().is_(True)
                                ),
                            ).where(*completed)
                        )
                    ).one()
                    value.update(paths=dict(paths), browser_seconds=browser_seconds, paid=paid)
                else:
                    # Successful commands are bounded summaries; do not invent percentiles
                    # from aggregated durations. Mean duration is measurable.
                    methods = (
                        func.jsonb_each(SessionEventRecord.payload["methods"])
                        .table_valued("key", "value")
                        .lateral()
                    )
                    command_fields = [
                        func.coalesce(
                            func.sum(cast(cast(methods.c.value, JSONB)[field].as_string(), Float)),
                            0,
                        )
                        for field in ("count", "failed_count", "interrupted_count", "duration_ms")
                    ]
                    commands = (
                        await database.execute(
                            select(*command_fields)
                            .select_from(SessionEventRecord)
                            .join(methods, true())
                            .join(
                                GatewaySession, GatewaySession.id == SessionEventRecord.session_id
                            )
                            .where(
                                GatewaySession.workload == "automation",
                                SessionEventRecord.event_type == "command.summary",
                                SessionEventRecord.occurred_at >= start,
                                SessionEventRecord.occurred_at <= now,
                            )
                        )
                    ).one()
                    value.update(
                        command_count=int(commands[0]),
                        failed_commands=int(commands[1]),
                        interrupted_commands=int(commands[2]),
                        mean_command_ms=commands[3] / commands[0] if commands[0] else None,
                    )
                output[workload] = value
        return output
