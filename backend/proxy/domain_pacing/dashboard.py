"""Bounded PostgreSQL projections of admission and completion facts."""

from datetime import timedelta
from typing import Literal

from sqlalchemy import func, select

from backend.db.models.domain_pacing import DomainPacingLease, DomainPacingState
from backend.db.models.domain_pacing import DomainPacingRequest as Fact
from backend.db.models.gateway import SessionEventRecord
from backend.events.registry import EventType
from backend.proxy.domain_pacing.repository import PacingRepository

Window = Literal["1h", "24h", "7d"]
WINDOWS = {"1h": (3600, 60), "24h": (86400, 900), "7d": (604800, 7200)}
REASONS = ("domain_spacing", "domain_concurrency", "domain_cooldown")


def counters(row) -> dict:
    return {
        "offered": row.offered,
        "admitted": row.admitted,
        "refusals": {reason: getattr(row, reason) for reason in REASONS},
    }


async def dashboard(repository: PacingRepository, window: Window, hostname: str | None) -> dict:
    seconds, bucket_seconds = WINDOWS[window]
    settings = await repository.settings()
    states = await repository.list_states(hostname=hostname, limit=500)
    async with repository._sessions() as database:
        now = await database.scalar(select(func.clock_timestamp()))
        starts = now - timedelta(seconds=seconds)
        admission_columns = [
            func.count().label("offered"),
            func.count().filter(Fact.refusal.is_(None)).label("admitted"),
            *[func.count().filter(Fact.refusal == reason).label(reason) for reason in REASONS],
        ]
        completion_columns = [
            func.count().filter(Fact.outcome == "throttled").label("origin_throttled"),
            func.count().filter(Fact.outcome == "overload").label("origin_overload"),
            func.avg(func.extract("epoch", Fact.finished_at - Fact.started_at)).label(
                "mean_capture_seconds"
            ),
        ]
        admission_filter = [Fact.started_at >= starts, Fact.started_at <= now]
        completion_filter = [Fact.finished_at >= starts, Fact.finished_at <= now]
        if hostname:
            admission_filter.append(Fact.hostname == hostname)
            completion_filter.append(Fact.hostname == hostname)
        totals = (await database.execute(select(*admission_columns).where(*admission_filter))).one()
        completion = (
            await database.execute(select(*completion_columns).where(*completion_filter))
        ).one()
        hosts = (
            await database.execute(
                select(Fact.hostname, *admission_columns)
                .where(
                    *admission_filter, Fact.hostname.in_([state["hostname"] for state in states])
                )
                .group_by(Fact.hostname)
            )
        ).all()
        host_counts = {row.hostname: counters(row) for row in hosts}
        for state in states:
            state["traffic"] = host_counts.get(
                state["hostname"],
                {"offered": 0, "admitted": 0, "refusals": dict.fromkeys(REASONS, 0)},
            )
            state["offered_per_second"] = state["traffic"]["offered"] / seconds
            state["admitted_per_second"] = state["traffic"]["admitted"] / seconds
        series = []
        history = []
        if hostname:

            def bucket(column):
                return func.floor(func.extract("epoch", column - starts) / bucket_seconds)

            admission_rows = (
                await database.execute(
                    select(
                        bucket(Fact.started_at).label("bucket"),
                        *admission_columns,
                        func.max(Fact.active_captures).label("peak_active"),
                        func.max(Fact.concurrency).label("maximum_allowance"),
                        func.min(Fact.spacing_seconds).label("minimum_spacing_seconds"),
                    )
                    .where(*admission_filter)
                    .group_by("bucket")
                )
            ).all()
            completion_rows = (
                await database.execute(
                    select(bucket(Fact.finished_at).label("bucket"), *completion_columns)
                    .where(*completion_filter)
                    .group_by("bucket")
                )
            ).all()
            admissions = {int(row.bucket): row for row in admission_rows}
            completions = {int(row.bucket): row for row in completion_rows}
            for index in range(seconds // bucket_seconds):
                admission = admissions.get(index)
                finished = completions.get(index)
                series.append(
                    {
                        "at": starts + timedelta(seconds=index * bucket_seconds),
                        "offered_per_second": admission.offered / bucket_seconds
                        if admission
                        else 0,
                        "admitted_per_second": admission.admitted / bucket_seconds
                        if admission
                        else 0,
                        "refusals": counters(admission)["refusals"]
                        if admission
                        else dict.fromkeys(REASONS, 0),
                        "peak_active": admission.peak_active if admission else None,
                        "maximum_allowance": admission.maximum_allowance if admission else None,
                        "minimum_spacing_seconds": admission.minimum_spacing_seconds
                        if admission
                        else None,
                        "origin_throttled": finished.origin_throttled if finished else 0,
                        "origin_overload": finished.origin_overload if finished else 0,
                        "mean_capture_seconds": finished.mean_capture_seconds if finished else None,
                    }
                )
            events = await database.scalars(
                select(SessionEventRecord)
                .where(
                    SessionEventRecord.event_type == EventType.DOMAIN_PACING_ADJUSTED,
                    SessionEventRecord.payload["hostname"].astext == hostname,
                    SessionEventRecord.occurred_at >= starts,
                    SessionEventRecord.occurred_at <= now,
                )
                .order_by(SessionEventRecord.id.desc())
                .limit(100)
            )
            history = [{"at": event.occurred_at, **event.payload} for event in events]
        active_filter = [DomainPacingLease.expires_at > now]
        cooldown_filter = [DomainPacingState.cooldown_until > now]
        if hostname:
            active_filter.append(DomainPacingLease.hostname == hostname)
            cooldown_filter.append(DomainPacingState.hostname == hostname)
        active_hosts = await database.scalar(
            select(func.count(func.distinct(DomainPacingLease.hostname))).where(*active_filter)
        )
        cooldown_hosts = await database.scalar(
            select(func.count()).select_from(DomainPacingState).where(*cooldown_filter)
        )
        throttled_hosts = await database.scalar(
            select(func.count(func.distinct(Fact.hostname))).where(
                *admission_filter, Fact.refusal.is_not(None)
            )
        )
        tracking_since = await database.scalar(select(func.min(Fact.started_at)))
        return {
            "window": window,
            "starts_at": starts,
            "ends_at": now,
            "tracking_since": tracking_since,
            "settings": settings,
            "domains": states,
            "totals": {
                **counters(totals),
                **dict(completion._mapping),
                "active_hosts": active_hosts,
                "cooldown_hosts": cooldown_hosts,
                "throttled_hosts": throttled_hosts,
            },
            "series": series,
            "history": history,
            "bucket_seconds": bucket_seconds,
            "domains_truncated": len(states) == 500,
        }
