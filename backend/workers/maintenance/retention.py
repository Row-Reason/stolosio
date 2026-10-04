from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import CaptureMethodCacheEntry, Domain, GatewaySession, SessionEventRecord
from backend.db.models.domain_pacing import (
    DomainPacingLease,
    DomainPacingRequest,
    DomainPacingState,
)


class RetentionJob:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        event_days: int,
        terminal_session_days: int,
        domain_days: int,
        method_cache_days: int,
        batch_size: int,
    ) -> None:
        self._sessions = sessions
        self._event_days = event_days
        self._terminal_session_days = terminal_session_days
        self._domain_days = domain_days
        self._method_cache_days = method_cache_days
        self._batch_size = batch_size

    async def run_once(self) -> dict[str, int]:
        now = datetime.now(UTC)
        deleted: dict[str, int] = {}
        async with self._sessions.begin() as database:
            event_ids = (
                select(SessionEventRecord.id)
                .where(
                    SessionEventRecord.occurred_at < now - timedelta(days=self._event_days),
                    SessionEventRecord.published_at.is_not(None),
                )
                .limit(self._batch_size)
            )
            result = await database.execute(
                delete(SessionEventRecord).where(SessionEventRecord.id.in_(event_ids))
            )
            deleted["session_events"] = result.rowcount

        async with self._sessions.begin() as database:
            session_ids = (
                select(GatewaySession.id)
                .where(
                    GatewaySession.state.in_(("closed", "failed")),
                    GatewaySession.closed_at < now - timedelta(days=self._terminal_session_days),
                )
                .limit(self._batch_size)
            )
            result = await database.execute(
                delete(GatewaySession).where(GatewaySession.id.in_(session_ids))
            )
            deleted["gateway_sessions"] = result.rowcount

        async with self._sessions.begin() as database:
            domain_ids = (
                select(Domain.id)
                .where(Domain.last_seen_at < now - timedelta(days=self._domain_days))
                .limit(self._batch_size)
            )
            result = await database.execute(delete(Domain).where(Domain.id.in_(domain_ids)))
            deleted["domains"] = result.rowcount

        async with self._sessions.begin() as database:
            # pagecapture treats entries unseen this long as expired anyway
            keys = (
                select(CaptureMethodCacheEntry.key)
                .where(
                    CaptureMethodCacheEntry.last_seen
                    < now - timedelta(days=self._method_cache_days)
                )
                .limit(self._batch_size)
            )
            result = await database.execute(
                delete(CaptureMethodCacheEntry).where(CaptureMethodCacheEntry.key.in_(keys))
            )
            deleted["capture_method_cache"] = result.rowcount
        async with self._sessions.begin() as database:
            pacing_now = await database.scalar(select(func.clock_timestamp()))
            # Lock in the same order as admission/release. Never purge an active lease or cooldown.
            live_lease = (
                select(DomainPacingLease.id)
                .where(
                    DomainPacingLease.hostname == DomainPacingState.hostname,
                    DomainPacingLease.expires_at > pacing_now,
                )
                .exists()
            )
            rows = list(
                await database.scalars(
                    select(DomainPacingState)
                    .where(
                        DomainPacingState.expires_at <= pacing_now,
                        DomainPacingState.next_start_at <= pacing_now,
                        or_(
                            DomainPacingState.cooldown_until.is_(None),
                            DomainPacingState.cooldown_until <= pacing_now,
                        ),
                        ~live_lease,
                    )
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                await database.delete(row)
            deleted["domain_pacing_state"] = len(rows)
        async with self._sessions.begin() as database:
            fact_ids = (
                select(DomainPacingRequest.id)
                .where(
                    DomainPacingRequest.started_at < now - timedelta(days=7),
                )
                .limit(self._batch_size)
            )
            result = await database.execute(
                delete(DomainPacingRequest).where(DomainPacingRequest.id.in_(fact_ids))
            )
            deleted["domain_pacing_requests"] = result.rowcount
        return deleted
