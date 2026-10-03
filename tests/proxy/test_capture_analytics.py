from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pagecapture import Assessment, Attempt, CaptureResult, Document

from backend.api.routes.admin_captures import router
from backend.db.models import CaptureResultRecord
from backend.proxy.capture.analytics import CaptureAnalytics, acquisition_outcome


@pytest.mark.parametrize(
    "tier,representation,expected",
    [
        ("managed", "rendered_html", "default"),
        ("local_resolution", "rendered_html", "internally_resolved"),
        ("challenge_resolution", "rendered_html", "externally_resolved"),
        ("local_resolution", "response_body", "default"),
    ],
)
def test_attribution_uses_content_source(tier, representation, expected):
    result = CaptureResult(
        "captured",
        "https://a.test",
        "https://a.test",
        "",
        "",
        document=Document(representation, "text/html", "utf-8", b"content"),
    )
    result.evidence.attempts = [
        Attempt("browser", tier, 200, 100, Assessment(None), "accept", "complete")
    ]
    assert acquisition_outcome(result) == expected
    result.outcome = "failed"
    assert acquisition_outcome(result) == "total_failure"


@pytest.mark.asyncio
async def test_dashboard_cohorts_and_window(database_sessions):
    now = datetime.now(UTC)
    async with database_sessions.begin() as db:
        for i, (outcome, enabled, challenged, age) in enumerate(
            [
                ("default", False, False, 0),
                ("internally_resolved", True, True, 0),
                ("externally_resolved", True, True, 0),
                ("total_failure", False, True, 0),
                ("total_failure", True, True, 0),
                ("internally_resolved", True, True, 10),
            ]
        ):
            db.add(
                CaptureResultRecord(
                    session_id=str(i),
                    completed_at=now - timedelta(days=age),
                    acquisition_outcome=outcome,
                    resolution_enabled=enabled,
                    challenge_detected=challenged,
                    local_attempted=enabled,
                    external_attempted=outcome == "externally_resolved",
                    paid=outcome == "externally_resolved",
                    duration_ms=1000,
                    local_seconds=1,
                    external_seconds=2 if outcome == "externally_resolved" else 0,
                )
            )
    analytics = CaptureAnalytics(database_sessions)
    result = await analytics.overview("7d")
    assert result["all_captures"]["total"] == 5
    assert result["all_captures"]["counts"]["total_failure"] == 2
    assert result["challenged_opt_in"]["total"] == 3
    assert result["challenged_opt_in"]["rates"]["internally_resolved"] == pytest.approx(1 / 3)
    assert result["all_captures"]["local_attempts"] == 3
    assert result["all_captures"]["external_attempts"] == 1
    assert (await analytics.overview("30d"))["all_captures"]["total"] == 6


@pytest.mark.asyncio
async def test_empty_dashboard_is_not_zero_percent_success(database_sessions):
    result = await CaptureAnalytics(database_sessions).overview("24h")
    assert result["tracking_since"] is None
    assert all(rate is None for rate in result["all_captures"]["rates"].values())


def test_dashboard_validates_window():
    app = FastAPI()
    app.include_router(router)
    app.state.capture_analytics = SimpleNamespace()
    with TestClient(app) as client:
        assert client.get("/v1/admin/captures/overview?window=forever").status_code == 422
