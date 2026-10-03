from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.proxy.contracts import ProviderName

router = APIRouter(prefix="/v1/admin/costs", tags=["admin"])


class CostTotalsResponse(BaseModel):
    session_count: int
    attempt_count: int
    failed_attempt_count: int
    modeled_cost_units: int
    chargeable_time_ms: int
    browser_connected_time_ms: int
    browserless_slot_time_ms: int


class ProviderCostResponse(BaseModel):
    provider: ProviderName
    attempt_count: int
    session_count: int
    failed_attempt_count: int
    modeled_cost_units: int
    chargeable_time_ms: int
    browser_connected_time_ms: int
    capacity_occupied_time_ms: int


class CostBucketResponse(BaseModel):
    started_at: str
    provider: ProviderName
    attempt_count: int
    modeled_cost_units: int
    chargeable_time_ms: int


class CostSessionResponse(BaseModel):
    workload: Literal["automation", "capture"]
    capture_hostname: str | None
    session_id: str
    client_reference: str | None
    closed_at: str | None
    providers: list[ProviderName]
    modeled_cost_units: int
    chargeable_time_ms: int


class CostOverviewResponse(BaseModel):
    window: Literal["24h", "7d", "30d", "90d"]
    starts_at: str
    ends_at: str
    finalized_through: str | None
    totals: CostTotalsResponse
    providers: list[ProviderCostResponse]
    buckets: list[CostBucketResponse]
    recent_sessions: list[CostSessionResponse]


@router.get("/overview", response_model=CostOverviewResponse)
async def cost_overview(
    request: Request,
    window: Literal["24h", "7d", "30d", "90d"] = Query(default="7d"),
    workload: Literal["automation", "capture"] | None = None,
) -> CostOverviewResponse:
    value = await request.app.state.costs.overview(window, workload=workload)
    return CostOverviewResponse.model_validate(value)


class CostRateResponse(BaseModel):
    provider: ProviderName
    cost_units_per_second: int
    updated_at: datetime


class CostRateUpdate(BaseModel):
    cost_units_per_second: int = Field(ge=0)


@router.get("/rates", response_model=list[CostRateResponse])
async def list_cost_rates(request: Request) -> list[CostRateResponse]:
    rows = await request.app.state.cost_rates.list()
    return [CostRateResponse.model_validate(row, from_attributes=True) for row in rows]


@router.patch("/rates/{provider}", response_model=CostRateResponse)
async def update_cost_rate(
    provider: ProviderName,
    update: CostRateUpdate,
    request: Request,
) -> CostRateResponse:
    row = await request.app.state.cost_rates.update(provider, update.cost_units_per_second)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown provider cost rate")
    return CostRateResponse.model_validate(row, from_attributes=True)
