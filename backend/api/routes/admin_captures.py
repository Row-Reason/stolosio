from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from backend.proxy.capture.analytics import AcquisitionOutcome

router = APIRouter(prefix="/v1/admin/captures", tags=["admin"])


class CaptureStats(BaseModel):
    total: int
    counts: dict[AcquisitionOutcome, int]
    rates: dict[AcquisitionOutcome, float | None]
    local_attempts: int
    external_attempts: int
    paid_captures: int
    local_seconds: float
    external_seconds: float
    mean_duration_ms: float | None


class CaptureOverview(BaseModel):
    window: Literal["24h", "7d", "30d", "90d"]
    starts_at: datetime
    ends_at: datetime
    tracking_since: datetime | None
    all_captures: CaptureStats
    challenged_opt_in: CaptureStats


@router.get("/overview", response_model=CaptureOverview)
async def overview(
    request: Request, window: Literal["24h", "7d", "30d", "90d"] = Query(default="7d")
):
    return await request.app.state.capture_analytics.overview(window)
