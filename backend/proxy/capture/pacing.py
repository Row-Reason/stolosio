"""Translate capture evidence into pacing facts; acquisition stays in pagecapture."""

from urllib.parse import urlsplit

from pagecapture import CaptureResult

from backend.proxy.domain_pacing.contracts import Observation
from backend.proxy.domain_pacing.service import normalize_hostname


def pacing_observation(result: CaptureResult) -> Observation:
    def same_host(url: str | None) -> bool:
        try:
            return normalize_hostname(
                urlsplit(result.requested_url).hostname or ""
            ) == normalize_hostname(urlsplit(url or "").hostname or "")
        except (ValueError, UnicodeError):
            return False

    attempts = result.evidence.attempts
    # An explicit origin throttle remains pacing evidence even if later verification
    # fails for content or a resolver succeeds. Attribute it to that attempt's host.
    throttles = [a for a in attempts if a.status_code == 429 and same_host(a.final_url)]
    if throttles:
        retries = [a.retry_after_seconds for a in throttles if a.retry_after_seconds is not None]
        return Observation("throttled", max(retries) if retries else None)
    latest = next((a for a in reversed(attempts) if a.final_url), None)
    if not same_host(latest.final_url if latest else result.final_url):
        return Observation("neutral")
    failure = result.failure
    if failure is not None:
        if failure.category != "website":
            if (
                failure.category == "content"
                and latest is not None
                and (
                    latest.status_code in (401, 403)
                    or (latest.status_code is not None and latest.status_code >= 500)
                )
            ):
                return Observation("overload", latest.retry_after_seconds)
            return Observation("neutral")
        if failure.code == "rate_limited":
            return Observation("throttled", failure.retry_after_seconds)
        # Repeated refusals of this client are how origins such as Companies House block a crawl.
        # A single denied page is not a backoff; the controller needs a streak without successes.
        if failure.code in ("website_error", "access_denied", "bot_blocked"):
            retry = (
                latest.retry_after_seconds
                if latest and latest.retry_after_seconds is not None
                else failure.retry_after_seconds
            )
            return Observation("overload", retry)
        return Observation("neutral")
    return Observation("healthy")
