"""Translate capture evidence into pacing facts; acquisition stays in pagecapture."""

from urllib.parse import urlsplit

from pagecapture import CaptureResult

from backend.proxy.domain_pacing.contracts import Observation
from backend.proxy.domain_pacing.service import normalize_hostname


def pacing_observation(result: CaptureResult) -> Observation:
    try:
        requested = normalize_hostname(urlsplit(result.requested_url).hostname or "")
        final = normalize_hostname(urlsplit(result.final_url).hostname or "")
    except (ValueError, UnicodeError):
        return Observation("neutral")
    # A redirect to another host is not evidence about the admitted host's capacity.
    if requested != final:
        return Observation("neutral")
    failure = result.failure
    if failure is not None:
        if failure.category != "website":
            return Observation("neutral")
        if failure.code == "rate_limited":
            return Observation("throttled", failure.retry_after_seconds)
        if failure.code == "website_error":
            return Observation("overload", failure.retry_after_seconds)
        return Observation("neutral")
    if any(attempt.status_code == 429 for attempt in result.evidence.attempts):
        return Observation("throttled")
    return Observation("healthy")
