import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pagecapture import CaptureRequest, CaptureResult
from pagecapture.failures import failure
from pagecapture.service import now

from backend.proxy.capture import CaptureUnavailable
from backend.proxy.domain_pacing import DomainThrottled
from backend.proxy.domain_pacing.service import normalize_hostname

router = APIRouter(tags=["capture"])


@router.post("/v1/capture")
async def capture(request: Request) -> JSONResponse:
    """A page's content as a person would receive it, or a failure that says why
    (packages/pagecapture/docs/api.md). 200 for every capture result, 400 for an invalid request,
    429 for domain pacing, 503 when no capacity is free; both include Retry-After."""
    try:
        capture_request = CaptureRequest.from_json(json.loads(await request.body()))
        normalize_hostname(urlsplit(capture_request.url).hostname or "")
    except (ValueError, UnicodeDecodeError) as error:
        return JSONResponse({"error": "invalid_request", "message": str(error)}, status_code=400)
    try:
        result = await request.app.state.capture.capture(capture_request)
    except (CaptureUnavailable, DomainThrottled) as error:
        started = now()
        refused = CaptureResult(
            outcome="failed",
            requested_url=capture_request.url,
            final_url=capture_request.url,
            started_at=started,
            finished_at=started,
            reference=capture_request.reference,
            failure=failure(
                "domain_throttled" if isinstance(error, DomainThrottled) else "capacity",
                error.reason,
                retry_after_seconds=error.retry_after_seconds,
            ),
        )
        return JSONResponse(
            refused.to_json(),
            status_code=429 if isinstance(error, DomainThrottled) else 503,
            headers={"Retry-After": str(error.retry_after_seconds)},
        )
    return JSONResponse(result.to_json())
