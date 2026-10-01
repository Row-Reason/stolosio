"""pagecapture: a page's content as a person would receive it, at the lowest cost that achieves it.

The public interface is the capture contract (docs/api.md):

    from pagecapture import CaptureRequest, CaptureService
    service = CaptureService()
    result = await service.capture(CaptureRequest(url="https://example.com/", resolve_bot_challenges=False))
    result.outcome            # "captured" (trustworthy document) or "failed" (with failure.code, category, transient)
    result.to_json()          # the capture endpoint's response body

or synchronously for one URL: `pagecapture.capture("https://example.com/")`.

A host service plugs in its own HTTP fetcher and browser tiers (pagecapture.adapters); the defaults use
httpx and CDP endpoints from settings (PAGECAPTURE_BROWSER_WS, PAGECAPTURE_CHALLENGE_BROWSER_WS).
"""

from .adapters import (
    BqlBrowserTier,
    BrowserTier,
    CdpBrowserTier,
    ChallengeNotPassed,
    EgressError,
    ExcludedUrl,
    Fetcher,
    FetchError,
    HostNotFound,
    HttpResponse,
    HttpxFetcher,
    RedirectLoop,
    UnsupportedMediaType,
)
from .api import (
    SCHEMA_VERSION,
    Assessment,
    Attempt,
    CaptureRequest,
    CaptureResult,
    Cost,
    Document,
    Evidence,
    Exclusion,
    Failure,
    Reason,
    Redirect,
    Response,
)
from .config import Settings
from .failures import FAILURES
from .service import CaptureService, capture

__all__ = [
    "CaptureService",
    "capture",
    "CaptureRequest",
    "CaptureResult",
    "Exclusion",
    "SCHEMA_VERSION",
    "Response",
    "Redirect",
    "Document",
    "Failure",
    "FAILURES",
    "Evidence",
    "Attempt",
    "Assessment",
    "Reason",
    "Cost",
    "Fetcher",
    "FetchError",
    "HostNotFound",
    "EgressError",
    "RedirectLoop",
    "ExcludedUrl",
    "UnsupportedMediaType",
    "HttpResponse",
    "HttpxFetcher",
    "BrowserTier",
    "CdpBrowserTier",
    "BqlBrowserTier",
    "ChallengeNotPassed",
    "Settings",
]
