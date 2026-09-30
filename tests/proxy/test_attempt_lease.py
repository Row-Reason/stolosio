from unittest.mock import AsyncMock

import pytest

from backend.proxy.attempts import AttemptAdmission, AttemptLease
from backend.proxy.contracts import (
    AttemptState,
    ProviderAttempt,
    ProviderName,
    ProviderSettingSchema,
    ResolvedSessionSettings,
    SessionSettingSchema,
    SessionState,
    StolosioSession,
)
from backend.proxy.postgres import AttemptAdmissionStatus
from backend.settings import Settings


class TransientDatabaseError(RuntimeError):
    sqlstate = "40P01"


def attempt() -> ProviderAttempt:
    return ProviderAttempt(
        attempt_id="00000000-0000-4000-8000-000000000002",
        session_id="00000000-0000-4000-8000-000000000001",
        ordinal=1,
        provider=ProviderName.BROWSERLESS,
        state=AttemptState.ACTIVE,
    )


@pytest.mark.asyncio
async def test_attempt_release_retries_a_transient_database_failure() -> None:
    repository = AsyncMock()
    repository.finish.side_effect = [TransientDatabaseError("deadlock"), True]
    notifier = AsyncMock()
    lease = AttemptLease(attempt(), repository, notifier)

    await lease.release(
        command_summary={"methods": {}},
        phase_summary={"measurement_version": 1},
    )
    await lease.release()

    assert repository.finish.await_count == 2
    assert repository.finish.await_args.kwargs["phase_summary"] == {
        "measurement_version": 1
    }
    notifier.notify.assert_awaited_once_with(ProviderName.BROWSERLESS)


@pytest.mark.asyncio
async def test_attempt_release_remains_retryable_after_nontransient_failure() -> None:
    repository = AsyncMock()
    repository.finish.side_effect = [RuntimeError("database unavailable"), True]
    notifier = AsyncMock()
    lease = AttemptLease(attempt(), repository, notifier)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await lease.release()
    await lease.release()

    assert repository.finish.await_count == 2
    notifier.notify.assert_awaited_once_with(ProviderName.BROWSERLESS)


def resolved() -> ResolvedSessionSettings:
    return ResolvedSessionSettings(
        provider=ProviderSettingSchema(slug=ProviderName.BROWSERLESS),
        session=SessionSettingSchema(),
        sources={},
    )


def session() -> StolosioSession:
    return StolosioSession(
        session_id="00000000-0000-4000-8000-000000000001",
        owner_id="owner",
        lease_token="token",
        state=SessionState.ADMITTED,
    )


@pytest.mark.asyncio
async def test_admission_retries_enqueue_and_claim_after_a_deadlock() -> None:
    queued = attempt()
    repository = AsyncMock()
    repository.enqueue.side_effect = [
        TransientDatabaseError("deadlock"),
        (AttemptAdmissionStatus.QUEUED, queued),
    ]
    repository.claim.side_effect = [TransientDatabaseError("deadlock"), queued]

    lease = await AttemptAdmission(repository, Settings(), notifier=AsyncMock()).acquire(
        session(), resolved()
    )

    assert lease.attempt == queued
    assert repository.enqueue.await_count == 2 and repository.claim.await_count == 2
    first, second = repository.enqueue.await_args_list
    assert first.args[1] == second.args[1]  # the rolled-back attempt id is reused


@pytest.mark.asyncio
async def test_admission_gives_up_on_a_persistent_deadlock() -> None:
    repository = AsyncMock()
    repository.enqueue.side_effect = TransientDatabaseError("deadlock")

    with pytest.raises(TransientDatabaseError):
        await AttemptAdmission(repository, Settings(), notifier=AsyncMock()).acquire(
            session(), resolved()
        )

    assert repository.enqueue.await_count == 3
