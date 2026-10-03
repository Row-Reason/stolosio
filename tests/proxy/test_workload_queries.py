from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.api.routes.admin_overview import OverviewResponse
from backend.db.models import AcquisitionAttempt, GatewaySession, SessionEventRecord
from backend.events import EventType, SessionEvent
from backend.proxy.costs import CostQueryService
from backend.proxy.session_queries import SessionFilters, SessionQueryService
from backend.proxy.workload_queries import WorkloadQueryService


def summary(tiers, *, outcome="captured", representation="response_body", seconds=0):
    return {
        "outcome": outcome,
        "tiers": tiers,
        "duration_ms": 2000,
        "representation": representation,
        "browser_seconds": seconds,
        "paid": "challenge_resolution" in tiers,
        "bytes": 3000,
        "attempts": [],
        **(
            {"failure_code": "bot_challenge", "failure_category": "website"}
            if outcome == "failed"
            else {}
        ),
    }


async def seed(database_sessions):
    now = datetime.now(UTC)
    rows = [
        GatewaySession(
            id=str(uuid4()),
            workload=workload,
            owner_id="test",
            lease_token=str(uuid4()),
            requested_settings={},
            state=state,
            capture_summary=capture,
            capture_hostname="example.test" if workload == "capture" else None,
            created_at=now - timedelta(days=2),
            closed_at=now - timedelta(minutes=10) if state in ("closed", "failed") else None,
            lease_expires_at=now + timedelta(minutes=10) if state == "open" else None,
            terminal_reason=reason,
        )
        for workload, state, capture, reason in [
            ("automation", "closed", None, "client_disconnected"),
            ("automation", "failed", None, "provider_unavailable"),
            ("automation", "open", None, None),
            ("capture", "closed", summary(["direct"]), "capture_completed"),
            # A render can still return response_body: it is NOT HTTP-only.
            ("capture", "closed", summary(["direct", "managed"], seconds=1), "capture_completed"),
            (
                "capture",
                "closed",
                summary(["direct", "challenge_resolution"], seconds=2),
                "capture_completed",
            ),
            # Normal session closure does NOT make a failed capture successful.
            ("capture", "closed", summary(["direct"], outcome="failed"), "capture_completed"),
            ("capture", "failed", None, "gateway_capacity_full"),
            ("capture", "failed", None, "client_disconnected"),
            ("capture", "open", None, None),
        ]
    ]
    async with database_sessions.begin() as database:
        database.add_all(rows)
        await database.flush()
        # Two attempts must not double-count their parent capture in outcome totals.
        for index in range(2):
            database.add(
                AcquisitionAttempt(
                    id=str(uuid4()),
                    session_id=rows[5].id,
                    ordinal=index + 1,
                    provider="browserless" if index == 0 else "browserless_cloud",
                    resolved_settings={},
                    setting_sources={},
                    state="completed",
                    capacity_occupied_ms=1000,
                    browser_connected_ms=500,
                    modeled_cost_units=10,
                    finished_at=now,
                )
            )
        command = SessionEvent.create(
            EventType.COMMAND_SUMMARY,
            uuid4(),
            payload={
                "methods": {
                    "Page.navigate": {
                        "count": 4,
                        "failed_count": 1,
                        "interrupted_count": 1,
                        "duration_ms": 800,
                        "provider_latency_ms": 400,
                        "stolosio_queue_ms": 0,
                    },
                }
            },
        )
        for session in (rows[0], rows[3]):
            database.add(
                SessionEventRecord(
                    session_id=session.id,
                    event_type="command.summary",
                    occurred_at=now,
                    payload=command.payload,
                )
            )
    return rows


@pytest.mark.asyncio
async def test_overview_separates_workloads_paths_outcomes_and_usage(database_sessions):
    await seed(database_sessions)
    overview = await WorkloadQueryService(database_sessions).overview("24h")
    OverviewResponse.model_validate(overview)
    automation, capture = overview["automation"], overview["capture"]
    assert automation["active"] == capture["active"] == 1
    assert automation["counts"] == {"closed": 1, "failed": 1}
    assert capture["counts"] == {"captured": 3, "failed": 1, "rejected": 1, "interrupted": 1}
    assert capture["paths"] == {"http": 1, "managed": 1, "challenge_resolution": 1}
    assert capture["browser_seconds"] == 3
    assert capture["capacity_ms"] == 2000
    assert capture["modeled_cost_units"] == 20
    assert capture["paid"] == 1
    assert automation["command_count"] == 4  # excludes internal capture commands
    assert automation["failed_commands"] == automation["interrupted_commands"] == 1
    assert automation["mean_command_ms"] == 200
    assert sum(row["success"] for row in capture["series"]) == 3
    assert sum(row["failed"] for row in capture["series"]) == 1
    assert sum(row["other"] for row in capture["series"]) == 2
    assert capture["median_duration_ms"] == 2000


@pytest.mark.asyncio
async def test_capture_history_filters_paginate_and_match_overview_window(database_sessions):
    rows = await seed(database_sessions)
    service = SessionQueryService(database_sessions)
    filters = SessionFilters(
        workload="capture", outcome="captured", since=datetime.now(UTC) - timedelta(days=1)
    )
    first = await service.sessions(filters, limit=2)
    second = await service.sessions(filters, before=first.next_cursor, limit=2)
    assert len(first.sessions) == 2
    assert len(second.sessions) == 1
    assert second.next_cursor is None
    assert {row["id"] for row in first.sessions + second.sessions} == {row.id for row in rows[3:6]}
    http = await service.sessions(
        SessionFilters(workload="capture", path="http", outcome="captured")
    )
    assert [row["id"] for row in http.sessions] == [rows[3].id]
    rejected = await service.sessions(SessionFilters(workload="capture", outcome="rejected"))
    assert [row["id"] for row in rejected.sessions] == [rows[7].id]
    failures = await service.sessions(SessionFilters(workload="capture", reason="bot_challenge"))
    assert [row["id"] for row in failures.sessions] == [rows[6].id]
    automation = await service.sessions(SessionFilters(workload="automation"))
    assert len(automation.sessions) == 3
    detail = await service.session(rows[4].id)
    assert detail["capture_path"] == "managed"
    assert detail["capture"]["representation"] == "response_body"
    costs = await CostQueryService(database_sessions).overview("24h", workload="capture")
    assert costs["totals"]["modeled_cost_units"] == 20
    costs = await CostQueryService(database_sessions).overview("24h", workload="automation")
    assert costs["totals"]["modeled_cost_units"] == 0


@pytest.mark.asyncio
async def test_empty_overview_is_explicit_and_zero_filled(database_sessions):
    overview = await WorkloadQueryService(database_sessions).overview("7d")
    OverviewResponse.model_validate(overview)
    for workload in ("automation", "capture"):
        assert overview[workload]["counts"] == {}
        assert overview[workload]["median_duration_ms"] is None
        assert len(overview[workload]["series"]) == 8
        assert all(row["success"] == 0 for row in overview[workload]["series"])


@pytest.mark.asyncio
async def test_capture_result_survives_event_retention(database_sessions):
    from sqlalchemy import delete

    rows = await seed(database_sessions)
    async with database_sessions.begin() as database:
        await database.execute(delete(SessionEventRecord))
    service = SessionQueryService(database_sessions)
    detail = await service.session(rows[4].id)
    assert detail["capture_outcome"] == "captured"
    assert detail["capture_path"] == "managed"
    overview = await WorkloadQueryService(database_sessions).overview("24h")
    assert overview["capture"]["counts"]["captured"] == 3
    assert overview["automation"]["command_count"] == 0
