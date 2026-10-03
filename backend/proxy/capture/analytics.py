from datetime import UTC, datetime
from typing import Literal

from pagecapture import CaptureResult
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import CaptureResultRecord
from backend.proxy.costs import COST_WINDOWS

AcquisitionOutcome = Literal[
    "default", "internally_resolved", "externally_resolved", "total_failure"
]
OUTCOMES = ("default", "internally_resolved", "externally_resolved", "total_failure")


def acquisition_outcome(result: CaptureResult) -> AcquisitionOutcome:
    if result.outcome != "captured":
        return "total_failure"
    if result.document and result.document.representation == "response_body":
        return "default"  # HTTP retained after a failed resolver belongs to normal acquisition.
    accepted = next((a for a in reversed(result.evidence.attempts) if a.decision == "accept"), None)
    if accepted and accepted.tier == "local_resolution":
        return "internally_resolved"
    if accepted and accepted.tier == "challenge_resolution":
        return "externally_resolved"
    return "default"


def capture_facts(result: CaptureResult, resolution_enabled: bool, duration_ms: int) -> dict:
    attempts = result.evidence.attempts
    return dict(
        acquisition_outcome=acquisition_outcome(result),
        resolution_enabled=resolution_enabled,
        challenge_detected=any(a.assessment.primary == "bot_challenge" for a in attempts),
        local_attempted=any(a.tier == "local_resolution" for a in attempts),
        external_attempted=any(a.tier == "challenge_resolution" for a in attempts),
        paid=result.evidence.cost.paid,
        duration_ms=duration_ms,
        local_seconds=sum(a.duration_ms / 1000 for a in attempts if a.tier == "local_resolution"),
        external_seconds=sum(
            a.duration_ms / 1000 for a in attempts if a.tier == "challenge_resolution"
        ),
    )


class CaptureAnalytics:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def overview(self, window: str) -> dict:
        ends_at = datetime.now(UTC)
        starts_at = ends_at - COST_WINDOWS[window].duration
        record = CaptureResultRecord
        async with self._sessions() as database:
            rows = (
                await database.execute(
                    select(
                        record.acquisition_outcome,
                        record.resolution_enabled,
                        record.challenge_detected,
                        func.count(),
                        func.sum(case((record.local_attempted, 1), else_=0)),
                        func.sum(case((record.external_attempted, 1), else_=0)),
                        func.sum(case((record.paid, 1), else_=0)),
                        func.sum(record.duration_ms),
                        func.sum(record.local_seconds),
                        func.sum(record.external_seconds),
                    )
                    .where(record.completed_at >= starts_at, record.completed_at <= ends_at)
                    .group_by(
                        record.acquisition_outcome,
                        record.resolution_enabled,
                        record.challenge_detected,
                    )
                )
            ).all()
            tracking_since = await database.scalar(select(func.min(record.completed_at)))

        def summarize(selected):
            counts = dict.fromkeys(OUTCOMES, 0)
            total = local = external = paid = duration = 0
            local_seconds = external_seconds = 0.0
            for outcome, _, _, n, ln, en, pn, ms, ls, es in selected:
                counts[outcome] += n
                total += n
                local += ln
                external += en
                paid += pn
                duration += ms
                local_seconds += ls
                external_seconds += es
            return dict(
                total=total,
                counts=counts,
                rates={k: v / total if total else None for k, v in counts.items()},
                local_attempts=local,
                external_attempts=external,
                paid_captures=paid,
                local_seconds=local_seconds,
                external_seconds=external_seconds,
                mean_duration_ms=duration / total if total else None,
            )

        return dict(
            window=window,
            starts_at=starts_at,
            ends_at=ends_at,
            tracking_since=tracking_since,
            all_captures=summarize(rows),
            challenged_opt_in=summarize([r for r in rows if r[1] and r[2]]),
        )
