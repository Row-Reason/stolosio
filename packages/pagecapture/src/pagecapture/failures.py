"""Failure codes of the capture contract (docs/api.md), and how assessment reasons map onto them."""

from .api import Failure

# code: (category, transient). Only the "website" category is evidence about a site's health.
FAILURES: dict[str, tuple[str, bool]] = {
    "rate_limited": ("website", True),
    "website_error": ("website", True),
    "not_found": ("website", False),
    "gone": ("website", False),
    "access_denied": ("website", False),
    "request_rejected": ("website", False),
    "paywall": ("website", False),
    "parked": ("website", False),
    "geo_blocked": ("website", False),
    "bot_challenge": ("website", False),  # a challenge a real browser can pass; resolvable on request
    "bot_blocked": ("website", False),  # a block page refusing this client/IP; only another identity helps
    "redirect_loop": ("website", False),  # the redirects don't end (a loop, or past the hop limit)
    "unreachable": ("network", True),
    "host_not_found": ("network", False),  # a resolver confirmed the host doesn't exist (NXDOMAIN) or has no address
    "capacity": ("gateway", True),
    "domain_throttled": ("gateway", True),
    "browser_unavailable": ("gateway", True),
    "deadline_exceeded": ("gateway", True),
    "incomplete_content": ("content", True),
    "interstitial": ("content", True),
    "unsupported_browser": ("content", False),
    "excluded": ("content", False),  # a redirect led to a URL the request excludes
    "unsupported_media_type": ("content", False),  # a media type outside the request's accept list
}

# Assessment reason (docs/labels.md) -> failure code, for reasons that end a capture. (No response at all and bot
# protection are decided by the service itself: unreachable, host_not_found, redirect_loop, bot_challenge /
# bot_blocked.)
REASON_FAILURE = {
    "rate_limited": "rate_limited",
    "geo_blocked": "geo_blocked",
    "unsupported_browser": "unsupported_browser",
    "interstitial": "interstitial",
    "auth": "access_denied",
    "paywall": "paywall",
    "parked": "parked",
    "gone": "gone",
    "not_found": "not_found",
    "server_error": "website_error",
}


def failure(
    code: str, message: str, retry_after_seconds: float | None = None, resolution_attempted: bool | None = None
) -> Failure:
    category, transient = FAILURES[code]
    return Failure(
        code=code,
        category=category,
        transient=transient,
        message=message,
        retry_after_seconds=retry_after_seconds,
        resolution_attempted=resolution_attempted,
    )


def from_reason(reason: str, status_code: int | None, detail: str, retry_after_seconds: float | None = None) -> Failure:
    if reason == "client_error":
        code = "access_denied" if status_code in (401, 403) else "request_rejected"
    else:
        code = REASON_FAILURE[reason]
    return failure(code, detail or reason, retry_after_seconds if FAILURES[code][1] else None)
