import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pagecapture import CaptureRequest, CaptureResult
from pagecapture.failures import failure
from pagecapture.service import now

from backend.proxy.capture import CaptureUnavailable

router = APIRouter(tags=["capture"])


@router.post("/v1/capture")
async def capture(request: Request) -> JSONResponse:
    """A page's content as a person would receive it, or a failure that says why
    (packages/pagecapture/docs/api.md). 200 for every capture result, 400 for an invalid request,
    503 with Retry-After when no capacity is free."""
    try:
        capture_request = CaptureRequest.from_json(json.loads(await request.body()))
    except (ValueError, UnicodeDecodeError) as error:
        return JSONResponse({"error": "invalid_request", "message": str(error)}, status_code=400)
    try:
        result = await request.app.state.capture.capture(capture_request)
    except CaptureUnavailable as error:
        started = now()
        refused = CaptureResult(
            outcome="failed",
            requested_url=capture_request.url,
            final_url=capture_request.url,
            started_at=started,
            finished_at=started,
            reference=capture_request.reference,
            failure=failure("capacity", error.reason),
        )
        return JSONResponse(
            refused.to_json(),
            status_code=503,
            headers={"Retry-After": str(error.retry_after_seconds)},
        )
    return JSONResponse(result.to_json())
