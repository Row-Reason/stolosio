from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from backend.proxy.domain_pacing.contracts import PacingSettings
from backend.proxy.domain_pacing.dashboard import Window, dashboard
from backend.proxy.domain_pacing.service import normalize_hostname

router = APIRouter(prefix="/v1/admin/domain-pacing", tags=["admin"])


class PacingSettingsResponse(PacingSettings):
    version: int


class DomainPacingResponse(BaseModel):
    hostname: str
    concurrency: int
    spacing_seconds: float
    expires_at: datetime
    cooldown_until: datetime | None
    healthy_samples: int
    concurrency_samples: int
    overload_samples: int
    generation: int
    reason: str
    adjusted_at: datetime | None
    expired: bool
    effective_concurrency: int
    effective_spacing_seconds: float
    active_captures: int


@router.get("/settings", response_model=PacingSettingsResponse)
async def get_settings(request: Request) -> dict:
    return await request.app.state.domain_pacing.repository.settings()


@router.put("/settings", response_model=PacingSettingsResponse)
async def update_settings(settings: PacingSettings, request: Request) -> dict:
    return await request.app.state.domain_pacing.repository.update_settings(settings.model_dump())


@router.get("", response_model=list[DomainPacingResponse])
async def list_domains(
    request: Request,
    hostname: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    try:
        normalized = normalize_hostname(hostname) if hostname else None
    except (ValueError, UnicodeError) as error:
        raise HTTPException(status_code=422, detail="Invalid hostname") from error
    return await request.app.state.domain_pacing.repository.list_states(
        hostname=normalized, limit=limit
    )


class Traffic(BaseModel):
    offered: int
    admitted: int
    refusals: dict[str, int]


class DashboardDomain(DomainPacingResponse):
    reset_requested: bool
    traffic: Traffic
    offered_per_second: float
    admitted_per_second: float


class DashboardTotals(Traffic):
    origin_throttled: int
    origin_overload: int
    mean_capture_seconds: float | None
    active_hosts: int
    cooldown_hosts: int
    throttled_hosts: int


class DashboardBucket(BaseModel):
    at: datetime
    offered_per_second: float
    admitted_per_second: float
    refusals: dict[str, int]
    peak_active: int | None
    maximum_allowance: int | None
    minimum_spacing_seconds: float | None
    origin_throttled: int
    origin_overload: int
    mean_capture_seconds: float | None


class Adjustment(BaseModel):
    at: datetime
    hostname: str
    concurrency: int
    spacing_seconds: float
    generation: int
    reason: str


class DashboardResponse(BaseModel):
    window: Window
    starts_at: datetime
    ends_at: datetime
    tracking_since: datetime | None
    settings: PacingSettingsResponse
    domains: list[DashboardDomain]
    totals: DashboardTotals
    series: list[DashboardBucket]
    history: list[Adjustment]
    bucket_seconds: int
    domains_truncated: bool


def normalized_host(hostname: str | None) -> str | None:
    try:
        return normalize_hostname(hostname) if hostname else None
    except (ValueError, UnicodeError) as error:
        raise HTTPException(status_code=422, detail="Invalid hostname") from error


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(request: Request, window: Window = "1h", hostname: str | None = None):
    return await dashboard(
        request.app.state.domain_pacing.repository, window, normalized_host(hostname)
    )


@router.post("/reset")
async def reset_domain(request: Request, hostname: str):
    normalized = normalized_host(hostname)
    if not normalized or not await request.app.state.domain_pacing.repository.request_reset(
        normalized
    ):
        raise HTTPException(status_code=404, detail="No learned policy for this hostname")
    return {"hostname": normalized, "reset_requested": True}
