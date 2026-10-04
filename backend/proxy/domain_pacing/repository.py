import math
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models.domain_pacing import (
    DomainPacingLease,
    DomainPacingRequest,
    DomainPacingSettings,
    DomainPacingState,
)
from backend.db.models.gateway import SessionEventRecord
from backend.events.registry import EventType, validate_payload
from backend.proxy.domain_pacing import controller
from backend.proxy.domain_pacing.contracts import (
    DomainThrottled,
    Lease,
    Observation,
    PacingSettings,
    Policy,
)


def policy_from_row(row: DomainPacingState) -> Policy:
    return Policy(**{field.name: getattr(row, field.name) for field in fields(Policy)})


def write_policy(row: DomainPacingState, policy: Policy) -> None:
    for field in fields(Policy):
        setattr(row, field.name, getattr(policy, field.name))


def record_adjustment(
    database: AsyncSession, session_id: str, row: DomainPacingState, now: datetime
) -> None:
    payload = validate_payload(
        EventType.DOMAIN_PACING_ADJUSTED,
        {
            "hostname": row.hostname,
            "concurrency": row.concurrency,
            "spacing_seconds": row.spacing_seconds,
            "reason": row.reason,
            "generation": row.generation,
        },
    )
    database.add(
        SessionEventRecord(
            session_id=session_id,
            event_type=EventType.DOMAIN_PACING_ADJUSTED,
            occurred_at=now,
            payload=payload,
            reason=row.reason,
        )
    )


class PacingRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def _settings(database: AsyncSession) -> DomainPacingSettings:
        existing = await database.get(DomainPacingSettings, "global")
        if existing is not None:
            return existing
        await database.execute(
            insert(DomainPacingSettings)
            .values(key="global", settings=PacingSettings().model_dump(), version=1)
            .on_conflict_do_nothing(index_elements=["key"])
        )
        row = await database.get(DomainPacingSettings, "global")
        assert row is not None
        return row

    async def settings(self) -> dict:
        async with self._sessions.begin() as database:
            row = await self._settings(database)
            return {**row.settings, "version": row.version}

    async def update_settings(self, changes: dict) -> dict:
        async with self._sessions.begin() as database:
            await self._settings(database)
            row = await database.get(DomainPacingSettings, "global", with_for_update=True)
            assert row is not None
            row.settings = PacingSettings.model_validate({**row.settings, **changes}).model_dump()
            row.version += 1
            return {**row.settings, "version": row.version}

    async def acquire(
        self, hostname: str, session_id: str, lease_seconds: float, *, lease_id: str | None = None
    ) -> Lease:
        refusal: DomainThrottled | None = None
        lease = Lease(lease_id or str(uuid4()), hostname)
        async with self._sessions.begin() as database:
            configuration = await self._settings(database)
            settings = PacingSettings.model_validate(configuration.settings)
            now = await database.scalar(select(func.clock_timestamp()))
            assert now is not None
            await database.execute(
                insert(DomainPacingState)
                .values(
                    hostname=hostname,
                    concurrency=settings.default_concurrency,
                    spacing_seconds=settings.default_spacing_seconds,
                    expires_at=now + timedelta(seconds=settings.learned_ttl_seconds),
                    next_start_at=now,
                    settings_version=configuration.version,
                )
                .on_conflict_do_nothing(index_elements=["hostname"])
            )
            row = await database.get(DomainPacingState, hostname, with_for_update=True)
            assert row is not None
            # Obtain time after locking: other replicas may have held the row while we waited.
            now = await database.scalar(select(func.clock_timestamp()))
            assert now is not None
            if (
                row.reset_requested
                or now >= row.expires_at
                or row.settings_version != configuration.version
            ):
                old_policy = policy_from_row(row)
                policy = controller.reset(settings, old_policy, now)
                if row.settings_version != configuration.version:
                    policy = replace(policy, reason="settings_changed")
                if row.reset_requested:
                    policy = replace(policy, reason="operator_reset")
                row.reset_requested = False
                write_policy(row, policy)
                row.spacing_refused_at = None
                row.settings_version = configuration.version
                record_adjustment(database, session_id, row, now)
            await database.execute(
                delete(DomainPacingLease).where(
                    DomainPacingLease.hostname == hostname, DomainPacingLease.expires_at <= now
                )
            )
            expiries = list(
                await database.scalars(
                    select(DomainPacingLease.expires_at).where(
                        DomainPacingLease.hostname == hostname
                    )
                )
            )
            if row.cooldown_until and row.cooldown_until > now:
                refusal = DomainThrottled(
                    "domain_cooldown", max(1, math.ceil((row.cooldown_until - now).total_seconds()))
                )
            elif now < row.next_start_at:
                row.spacing_refused_at = now
                refusal = DomainThrottled(
                    "domain_spacing", max(1, math.ceil((row.next_start_at - now).total_seconds()))
                )
            elif len(expiries) >= row.concurrency:
                # A refused caller proves demand beyond the occupied allowance. In particular,
                # concurrency=1 must not interpret every sparse capture as pressure.
                await database.execute(
                    update(DomainPacingLease)
                    .where(DomainPacingLease.hostname == hostname)
                    .values(at_limit=True, concurrency_at_limit=True)
                )
                # A capture may release sooner; this is a bounded polling hint, not a reservation.
                delay = min(5.0, (min(expiries) - now).total_seconds())
                refusal = DomainThrottled("domain_concurrency", max(1, math.ceil(delay)))
            else:
                concurrency_at_limit = bool(expiries) and len(expiries) + 1 >= row.concurrency
                spacing_at_limit = (
                    row.last_started_at is not None
                    and (now - row.last_started_at).total_seconds() <= row.spacing_seconds * 1.5
                )
                recent_spacing_demand = row.spacing_refused_at is not None and (
                    now - row.spacing_refused_at
                ).total_seconds() <= max(2, row.spacing_seconds * 1.5)
                database.add(
                    DomainPacingLease(
                        id=lease.id,
                        hostname=hostname,
                        session_id=session_id,
                        expires_at=now + timedelta(seconds=lease_seconds),
                        generation=row.generation,
                        at_limit=concurrency_at_limit or spacing_at_limit or recent_spacing_demand,
                        concurrency_at_limit=concurrency_at_limit,
                    )
                )
                row.next_start_at = now + timedelta(seconds=row.spacing_seconds)
                row.last_started_at = now
                row.spacing_refused_at = None
            database.add(
                DomainPacingRequest(
                    id=lease.id,
                    hostname=hostname,
                    started_at=now,
                    lease_expires_at=None if refusal else now + timedelta(seconds=lease_seconds),
                    refusal=refusal.reason if refusal else None,
                    active_captures=len(expiries) + (0 if refusal else 1),
                    concurrency=row.concurrency,
                    spacing_seconds=row.spacing_seconds,
                )
            )
        # Commit expiry/reset even when admission refuses.
        if refusal is not None:
            raise refusal
        return lease

    async def release(self, lease: Lease, observation: Observation | None = None) -> None:
        async with self._sessions.begin() as database:
            row = await database.get(DomainPacingState, lease.hostname, with_for_update=True)
            if row is None:
                return
            held = await database.get(DomainPacingLease, lease.id)
            if held is None:
                return
            now = await database.scalar(select(func.clock_timestamp()))
            assert now is not None
            configuration = await self._settings(database)
            if observation is not None and held.expires_at > now:
                settings = PacingSettings.model_validate(configuration.settings)
                if (
                    row.reset_requested
                    or row.expires_at <= now
                    or row.settings_version != configuration.version
                ):
                    policy = controller.reset(settings, policy_from_row(row), now)
                    if row.settings_version != configuration.version:
                        policy = replace(policy, reason="settings_changed")
                    if row.reset_requested:
                        policy = replace(policy, reason="operator_reset")
                    row.reset_requested = False
                    write_policy(row, policy)
                    row.spacing_refused_at = None
                    row.settings_version = configuration.version
                    record_adjustment(database, held.session_id, row, now)
                before = policy_from_row(row)
                after = controller.update(
                    settings,
                    before,
                    observation,
                    now,
                    at_limit=held.at_limit,
                    concurrency_at_limit=held.concurrency_at_limit,
                    generation=held.generation,
                )
                write_policy(row, after)
                if after.generation != before.generation:
                    if row.last_started_at is not None:
                        row.next_start_at = max(
                            row.next_start_at,
                            row.last_started_at + timedelta(seconds=after.spacing_seconds),
                        )
                    record_adjustment(database, held.session_id, row, now)
            await database.execute(
                update(DomainPacingRequest)
                .where(DomainPacingRequest.id == lease.id)
                .values(
                    finished_at=now, outcome=observation.outcome if observation else "interrupted"
                )
            )
            await database.delete(held)

    async def list_states(self, *, hostname: str | None = None, limit: int = 100) -> list[dict]:
        async with self._sessions.begin() as database:
            configuration = await self._settings(database)
            settings = PacingSettings.model_validate(configuration.settings)
            now = await database.scalar(select(func.clock_timestamp()))
            active_count = (
                select(func.count())
                .select_from(DomainPacingLease)
                .where(
                    DomainPacingLease.hostname == DomainPacingState.hostname,
                    DomainPacingLease.expires_at > now,
                )
                .correlate(DomainPacingState)
                .scalar_subquery()
            )
            statement = (
                select(DomainPacingState, active_count)
                .order_by(DomainPacingState.hostname)
                .limit(limit)
            )
            if hostname:
                statement = statement.where(DomainPacingState.hostname == hostname)
            rows = (await database.execute(statement)).all()
            result = []
            for row, active in rows:
                expired = (
                    row.reset_requested
                    or row.expires_at <= now
                    or row.settings_version != configuration.version
                )
                policy = policy_from_row(row)
                effective = controller.reset(settings, policy, now) if expired else policy
                result.append(
                    {
                        "hostname": row.hostname,
                        **asdict(policy),
                        "expired": expired,
                        "reset_requested": row.reset_requested,
                        "effective_concurrency": effective.concurrency,
                        "effective_spacing_seconds": effective.spacing_seconds,
                        "active_captures": active,
                    }
                )
            return result

    async def request_reset(self, hostname: str) -> bool:
        async with self._sessions.begin() as database:
            row = await database.get(DomainPacingState, hostname, with_for_update=True)
            if row is None:
                return False
            # Apply and publish on the next capture transaction. Existing leases/cooldowns survive.
            row.reset_requested = True
            return True
