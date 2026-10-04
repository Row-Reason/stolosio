import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.routes.admin_domain_pacing import router
from backend.db.models import (
    DomainPacingLease,
    DomainPacingState,
    GatewaySession,
    SessionEventRecord,
)
from backend.events import SessionEvent
from backend.proxy.domain_pacing import DomainPacing, DomainThrottled, PacingRepository
from backend.proxy.domain_pacing.contracts import Observation, PacingSettings, Policy
from backend.proxy.domain_pacing.controller import reset, update
from backend.proxy.domain_pacing.service import normalize_hostname

NOW = datetime(2026, 10, 4, tzinfo=UTC)
SETTINGS = PacingSettings()


def policy(**changes):
    return replace(Policy(2, 1, NOW + timedelta(days=1)), **changes)


def learn(value, observation, **changes):
    arguments = {"at_limit": True, "concurrency_at_limit": False, "generation": value.generation}
    return update(SETTINGS, value, observation, NOW, **(arguments | changes))


def test_healthy_demand_learns_spacing_and_refreshes_ttl():
    value = policy(expires_at=NOW + timedelta(seconds=60))
    for _ in range(SETTINGS.healthy_samples):
        value = learn(value, Observation("healthy"))
    assert value.spacing_seconds == 0.9
    assert value.concurrency == 2
    assert value.expires_at == NOW + timedelta(days=1)
    assert value.reason == "healthy_at_limit"


def test_concurrency_increases_independently_when_exercised():
    value = policy()
    for _ in range(SETTINGS.healthy_samples):
        value = learn(value, Observation("healthy"), concurrency_at_limit=True)
    assert value.concurrency == 3 and value.spacing_seconds == 1


def test_sparse_traffic_does_not_raise_allowance_or_renew_ttl():
    value = policy()
    for _ in range(100):
        value = learn(value, Observation("healthy"), at_limit=False)
    assert value == policy()


def test_explicit_throttling_backs_off_and_stale_success_cannot_undo_it():
    before = policy(concurrency=8, spacing_seconds=0.1)
    after = learn(before, Observation("throttled", 120))
    assert after.concurrency == 4 and after.spacing_seconds == 0.2
    assert after.cooldown_until == NOW + timedelta(seconds=120)
    assert learn(after, Observation("healthy"), generation=before.generation) == after
    assert learn(after, Observation("throttled", 1)).cooldown_until == after.cooldown_until


def test_one_burst_reduces_once_but_old_refusal_can_extend_cooldown():
    before = policy(concurrency=8, spacing_seconds=0.1)
    after = learn(before, Observation("throttled", 30))
    extended = learn(after, Observation("throttled", 120), generation=before.generation)
    assert extended.concurrency == 4 and extended.spacing_seconds == 0.2
    assert extended.cooldown_until == NOW + timedelta(seconds=120)
    assert learn(extended, Observation("overload"), generation=before.generation) == extended


def test_repeated_overload_required_and_success_breaks_streak():
    value = learn(policy(), Observation("overload"))
    assert value.concurrency == 2 and value.cooldown_until is None
    value = learn(value, Observation("healthy"), at_limit=False)
    assert value.overload_samples == 0
    for _ in range(3):
        value = learn(value, Observation("overload"))
    assert value.concurrency == 1 and value.spacing_seconds == 2
    assert value.cooldown_until == NOW + timedelta(seconds=30)


def test_ttl_reset_preserves_cooldown_and_discards_learning():
    before = policy(
        concurrency=8,
        spacing_seconds=0.1,
        healthy_samples=19,
        cooldown_until=NOW + timedelta(hours=1),
    )
    after = reset(SETTINGS, before, NOW)
    assert after.concurrency == 2 and after.spacing_seconds == 1
    assert after.healthy_samples == 0 and after.generation == 1
    assert after.cooldown_until == before.cooldown_until


def test_learning_respects_bounds_and_neutral_outcomes():
    value = policy(concurrency=1, spacing_seconds=60)
    value = learn(value, Observation("throttled"))
    assert value.concurrency == 1 and value.spacing_seconds == 60
    assert learn(value, Observation("neutral")) == value
    value = policy(spacing_seconds=0.1)
    for _ in range(40):
        value = learn(value, Observation("healthy"))
    assert value.spacing_seconds == 0.1


@pytest.mark.parametrize(
    "changes",
    [
        {"default_concurrency": 9},
        {"default_spacing_seconds": 0.01},
        {"learned_ttl_seconds": 0},
        {"minimum_spacing_seconds": float("nan")},
    ],
)
def test_invalid_settings_rejected(changes):
    with pytest.raises(ValidationError):
        PacingSettings(**changes)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("EXAMPLE.com.", "example.com"),
        ("例え.jp", "xn--r8jz45g.jp"),
        ("2001:0db8::1", "2001:db8::1"),
    ],
)
def test_host_normalization(host, expected):
    assert normalize_hostname(host) == expected


@pytest_asyncio.fixture
async def pacing(database_sessions):
    session_id = str(uuid4())
    async with database_sessions.begin() as database:
        database.add(
            GatewaySession(
                id=session_id,
                owner_id=str(uuid4()),
                lease_token=str(uuid4()),
                requested_settings={},
                state="open",
                workload="capture",
            )
        )
    return DomainPacing(PacingRepository(database_sessions)), session_id


async def allow_next(database_sessions, host="example.test"):
    async with database_sessions.begin() as database:
        row = await database.get(DomainPacingState, host, with_for_update=True)
        row.next_start_at = datetime.now(UTC) - timedelta(seconds=1)


@pytest.mark.asyncio
async def test_replicas_serialize_starts_and_hosts_are_independent(pacing, database_sessions):
    service, session_id = pacing
    replica = DomainPacing(PacingRepository(database_sessions))
    results = await asyncio.gather(
        *[
            (service if i % 2 else replica).acquire("EXAMPLE.test.", session_id, 120)
            for i in range(12)
        ],
        return_exceptions=True,
    )
    assert sum(not isinstance(value, Exception) for value in results) == 1
    failures = [value for value in results if isinstance(value, DomainThrottled)]
    assert len(failures) == 11 and all(value.reason == "domain_spacing" for value in failures)
    await replica.acquire("other.test", session_id, 120)
    async with database_sessions() as database:
        assert len(list(await database.scalars(select(DomainPacingLease)))) == 2


@pytest.mark.asyncio
async def test_concurrency_release_and_crash_expiry(pacing, database_sessions):
    service, session_id = pacing
    first = await service.acquire("example.test", session_id, 120)
    await allow_next(database_sessions)
    second = await service.acquire("example.test", session_id, 120)
    await allow_next(database_sessions)
    with pytest.raises(DomainThrottled, match="domain_concurrency"):
        await service.acquire("example.test", session_id, 120)
    await service.release(first)
    await service.release(first)
    third = await service.acquire("example.test", session_id, 120)
    async with database_sessions.begin() as database:
        row = await database.get(DomainPacingLease, second.id)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await allow_next(database_sessions)
    await service.acquire("example.test", session_id, 120)
    async with database_sessions() as database:
        assert await database.get(DomainPacingLease, second.id) is None
        assert await database.get(DomainPacingLease, third.id) is not None


@pytest.mark.asyncio
async def test_ttl_never_erases_active_leases_or_cooldown(pacing, database_sessions):
    service, session_id = pacing
    lease = await service.acquire("example.test", session_id, 120)
    async with database_sessions.begin() as database:
        row = await database.get(DomainPacingState, "example.test", with_for_update=True)
        row.concurrency, row.spacing_seconds = 8, 0.1
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        row.cooldown_until = datetime.now(UTC) + timedelta(seconds=120)
    with pytest.raises(DomainThrottled, match="domain_cooldown"):
        await service.acquire("example.test", session_id, 120)
    async with database_sessions() as database:
        row = await database.get(DomainPacingState, "example.test")
        assert row.concurrency == 2 and row.spacing_seconds == 1
        assert await database.get(DomainPacingLease, lease.id) is not None


@pytest.mark.asyncio
async def test_learned_allowance_survives_new_repository_and_adjustment_is_idempotent(
    pacing, database_sessions
):
    service, session_id = pacing
    await service.repository.update_settings({"healthy_samples": 2})
    warmup = await service.acquire("example.test", session_id, 120)
    await service.release(warmup)
    for _ in range(2):
        await allow_next(database_sessions)
        lease = await service.acquire("example.test", session_id, 120)
        await service.release(lease, Observation("healthy"))
        await service.release(lease, Observation("healthy"))
    replica = DomainPacing(PacingRepository(database_sessions))
    states = await replica.repository.list_states(hostname="example.test")
    assert states[0]["spacing_seconds"] == 0.9
    async with database_sessions() as database:
        events = list(await database.scalars(select(SessionEventRecord)))
    assert len(events) == 1
    assert events[0].payload["reason"] == "healthy_at_limit"
    # The outbox event is valid for delivery/replay and contains no URL, headers or document.
    SessionEvent.from_json(
        SessionEvent.create(events[0].event_type, uuid4(), payload=events[0].payload).to_json()
    )


@pytest.mark.asyncio
async def test_saved_settings_are_not_reconciled_and_new_bounds_reset_policy(
    pacing, database_sessions
):
    service, session_id = pacing
    await service.acquire("example.test", session_id, 120)
    await service.repository.update_settings({"default_concurrency": 1})
    assert (await PacingRepository(database_sessions).settings())["default_concurrency"] == 1
    states = await service.repository.list_states()
    assert states[0]["expired"] and states[0]["effective_concurrency"] == 1
    await allow_next(database_sessions)
    with pytest.raises(DomainThrottled, match="domain_concurrency"):
        await service.acquire("example.test", session_id, 120)


@pytest.mark.asyncio
async def test_throttle_at_policy_expiry_still_establishes_cooldown(pacing, database_sessions):
    service, session_id = pacing
    lease = await service.acquire("example.test", session_id, 120)
    async with database_sessions.begin() as database:
        row = await database.get(DomainPacingState, "example.test", with_for_update=True)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await service.release(lease, Observation("throttled", 120))
    with pytest.raises(DomainThrottled, match="domain_cooldown"):
        await service.acquire("example.test", session_id, 120)


@pytest.mark.asyncio
async def test_single_slot_requires_demand_to_learn_upwards(pacing, database_sessions):
    service, session_id = pacing
    await service.repository.update_settings({"default_concurrency": 1, "healthy_samples": 2})
    for _ in range(2):
        lease = await service.acquire("example.test", session_id, 120)
        await service.release(lease, Observation("healthy"))
        async with database_sessions.begin() as database:
            row = await database.get(DomainPacingState, "example.test", with_for_update=True)
            row.next_start_at = row.last_started_at = datetime.now(UTC) - timedelta(seconds=10)
    assert (await service.repository.list_states())[0]["healthy_samples"] == 0
    for _ in range(2):
        lease = await service.acquire("example.test", session_id, 120)
        await allow_next(database_sessions)
        with pytest.raises(DomainThrottled, match="domain_concurrency"):
            await service.acquire("example.test", session_id, 120)
        await service.release(lease, Observation("healthy"))
    assert (await service.repository.list_states())[0]["concurrency"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal_age", [0, 10])
async def test_spacing_refusal_is_demand_despite_coarse_client_retry_timing(
    pacing, database_sessions, refusal_age
):
    service, session_id = pacing
    warmup = await service.acquire("example.test", session_id, 120)
    await service.release(warmup)
    with pytest.raises(DomainThrottled, match="domain_spacing"):
        await service.acquire("example.test", session_id, 120)
    async with database_sessions.begin() as database:
        row = await database.get(DomainPacingState, "example.test", with_for_update=True)
        row.spacing_seconds = 0.31381
        row.next_start_at = datetime.now(UTC) - timedelta(seconds=1)
        # The admitted interval lies outside the old 1.5*spacing heuristic.
        row.last_started_at = datetime.now(UTC) - timedelta(seconds=0.6)
        row.spacing_refused_at -= timedelta(seconds=refusal_age)
    lease = await service.acquire("example.test", session_id, 120)
    await service.release(lease, Observation("healthy"))
    states = await service.repository.list_states()
    assert states[0]["healthy_samples"] == (1 if refusal_age == 0 else 0)


@pytest.mark.asyncio
async def test_retention_preserves_live_leases_and_cooldowns(pacing, database_sessions):
    from backend.workers.maintenance.retention import RetentionJob

    service, session_id = pacing
    first = await service.acquire("active.test", session_id, 120)
    second = await service.acquire("cooldown.test", session_id, 120)
    third = await service.acquire("expired.test", session_id, 120)
    await service.release(second, Observation("throttled", 120))
    await service.release(third)
    async with database_sessions.begin() as database:
        rows = list(await database.scalars(select(DomainPacingState)))
        for row in rows:
            row.expires_at = row.next_start_at = datetime.now(UTC) - timedelta(seconds=1)
    job = RetentionJob(
        database_sessions,
        event_days=30,
        terminal_session_days=90,
        domain_days=365,
        method_cache_days=30,
        batch_size=100,
    )
    deleted = await job.run_once()
    assert deleted["domain_pacing_state"] == 1
    async with database_sessions() as database:
        assert await database.get(DomainPacingState, "active.test") is not None
        assert await database.get(DomainPacingState, "cooldown.test") is not None
        assert await database.get(DomainPacingState, "expired.test") is None
        assert await database.get(DomainPacingLease, first.id) is not None


def test_admin_settings_validation_and_state_normalization():
    class Repository:
        async def settings(self):
            return {**PacingSettings().model_dump(), "version": 1}

        async def update_settings(self, changes):
            return {**changes, "version": 2}

        async def list_states(self, *, hostname, limit):
            assert hostname == "example.com" and limit == 100
            return []

    app = FastAPI()
    app.state.domain_pacing = DomainPacing(Repository())
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/v1/admin/domain-pacing/settings").json()["default_concurrency"] == 2
        response = client.put("/v1/admin/domain-pacing/settings", json={"default_concurrency": 9})
        assert response.status_code == 422
        response = client.put("/v1/admin/domain-pacing/settings", json=SETTINGS.model_dump())
        assert response.status_code == 200 and response.json()["version"] == 2
        assert client.get("/v1/admin/domain-pacing?hostname=EXAMPLE.com.").json() == []


@pytest.mark.asyncio
async def test_dashboard_separates_refusals_from_target_signals_and_release_is_idempotent(
    pacing, database_sessions
):
    from backend.api.routes.admin_domain_pacing import DashboardResponse
    from backend.db.models import DomainPacingRequest
    from backend.proxy.domain_pacing.dashboard import dashboard

    service, session_id = pacing
    lease = await service.acquire("example.test", session_id, 120)
    with pytest.raises(DomainThrottled, match="domain_spacing"):
        await service.acquire("example.test", session_id, 120)
    await service.release(lease, Observation("throttled", 60))
    await service.release(lease, Observation("healthy"))
    with pytest.raises(DomainThrottled, match="domain_cooldown"):
        await service.acquire("example.test", session_id, 120)
    data = DashboardResponse.model_validate(
        await dashboard(service.repository, "1h", "example.test")
    )
    assert data.totals.offered == 3 and data.totals.admitted == 1
    assert data.totals.refusals == {
        "domain_spacing": 1,
        "domain_cooldown": 1,
        "domain_concurrency": 0,
    }
    assert data.totals.origin_throttled == 1 and data.totals.origin_overload == 0
    assert data.totals.cooldown_hosts == 1 and data.totals.active_hosts == 0
    assert len(data.series) == 60
    assert sum(bucket.origin_throttled for bucket in data.series) == 1
    assert sum(bucket.refusals["domain_cooldown"] for bucket in data.series) == 1
    assert data.history[0].reason == "origin_throttled"
    async with database_sessions() as database:
        facts = list(await database.scalars(select(DomainPacingRequest)))
        assert len(facts) == 3
        assert (await database.get(DomainPacingRequest, lease.id)).outcome == "throttled"


@pytest.mark.asyncio
async def test_dashboard_completion_window_independent_of_admission_window(
    pacing, database_sessions
):
    from backend.db.models import DomainPacingRequest
    from backend.proxy.domain_pacing.dashboard import dashboard

    service, session_id = pacing
    lease = await service.acquire("example.test", session_id, 120)
    async with database_sessions.begin() as database:
        fact = await database.get(DomainPacingRequest, lease.id)
        fact.started_at -= timedelta(hours=2)
    await service.release(lease, Observation("overload"))
    data = await dashboard(service.repository, "1h", "example.test")
    assert data["totals"]["offered"] == 0
    assert data["totals"]["origin_overload"] == 1
    assert sum(bucket["origin_overload"] for bucket in data["series"]) == 1
    other = await dashboard(service.repository, "1h", "other.test")
    assert other["totals"]["origin_overload"] == 0 and other["domains"] == []


@pytest.mark.asyncio
async def test_operator_reset_preserves_cooldown_and_publishes_when_applied(
    pacing, database_sessions
):
    service, session_id = pacing
    lease = await service.acquire("example.test", session_id, 120)
    await service.release(lease, Observation("throttled", 60))
    assert await service.repository.request_reset("missing.test") is False
    assert await service.repository.request_reset("example.test") is True
    before = (await service.repository.list_states())[0]
    assert before["effective_concurrency"] == 2 and before["reset_requested"]
    with pytest.raises(DomainThrottled, match="domain_cooldown"):
        await service.acquire("example.test", session_id, 120)
    after = (await service.repository.list_states())[0]
    assert after["concurrency"] == 2 and after["spacing_seconds"] == 1
    assert after["cooldown_until"] == before["cooldown_until"]
    assert after["reset_requested"] is False
    async with database_sessions() as database:
        events = list(
            await database.scalars(select(SessionEventRecord).order_by(SessionEventRecord.id))
        )
        assert events[-1].payload["reason"] == "operator_reset"


@pytest.mark.asyncio
async def test_pacing_traffic_retention_independent_of_learned_policy(pacing, database_sessions):
    from backend.db.models import DomainPacingRequest
    from backend.workers.maintenance.retention import RetentionJob

    service, session_id = pacing
    lease = await service.acquire("example.test", session_id, 120)
    await service.release(lease)
    async with database_sessions.begin() as database:
        fact = await database.get(DomainPacingRequest, lease.id)
        fact.started_at -= timedelta(days=8)
    job = RetentionJob(
        database_sessions,
        event_days=30,
        terminal_session_days=90,
        domain_days=365,
        method_cache_days=30,
        batch_size=100,
    )
    deleted = await job.run_once()
    assert deleted["domain_pacing_requests"] == 1
    assert (await service.repository.list_states())[0]["hostname"] == "example.test"
