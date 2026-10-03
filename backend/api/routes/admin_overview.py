from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class OutcomeBucket(BaseModel):
    at: str
    success: int
    failed: int
    other: int


class FailureCount(BaseModel):
    reason: str
    count: int


class WorkloadOverview(BaseModel):
    active: int
    counts: dict[str, int]
    median_duration_ms: float | None
    p95_duration_ms: float | None
    capacity_ms: int
    browser_ms: int
    modeled_cost_units: int
    series: list[OutcomeBucket]
    failures: list[FailureCount]


class AutomationOverview(WorkloadOverview):
    command_count: int
    failed_commands: int
    interrupted_commands: int
    mean_command_ms: float | None


class CaptureOverview(WorkloadOverview):
    paths: dict[str, int]
    browser_seconds: float
    paid: int


class OverviewResponse(BaseModel):
    window: Literal["24h", "7d", "30d"]
    starts_at: str
    ends_at: str
    automation: AutomationOverview
    capture: CaptureOverview


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    request: Request, window: Literal["24h", "7d", "30d"] = "24h"
) -> OverviewResponse:
    return OverviewResponse.model_validate(
        await request.app.state.workload_queries.overview(window)
    )
