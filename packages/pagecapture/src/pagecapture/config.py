"""All tunables in one place. Defaults reflect the benchmarks in docs/benchmarks.md."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from .fetch import USER_AGENT

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent.parent


@dataclass
class Settings:
    # ---- data (benchmarks only) ----
    labels_csv: Path = REPO_DIR / "data" / "labels.csv"
    snapshot: Path = REPO_DIR / "data" / "snapshot.jsonl.gz"

    # ---- classification ----
    # Stop at the first rule rejection at least this sure (skipping the rest of the rules).
    early_exit_confidence: float = 0.9

    # ---- capture service (see docs/api.md) ----
    capture_cap_s: float = 120.0  # whole capture, unless the request's deadline is shorter
    http_timeout_s: float = 20.0
    http_max_response_bytes: int = 10 * 1024 * 1024  # a larger plain body is not read to the end: the page renders
    user_agent: str = USER_AGENT  # the plain fetch and the managed render (the challenge tier keeps its own)

    # ---- method cache: skip rendering where plain HTTP has proven enough (see cache.py) ----
    method_cache_path: str | None = field(
        default_factory=lambda: os.environ.get("PAGECAPTURE_METHOD_CACHE")
    )  # SQLite file; unset = in memory
    cache_ttl_days: float = 30.0
    sufficient_coverage: float = 0.95  # plain response holds at least this share of the rendered content
    pattern_min_comparisons: int = 3  # sufficient comparisons before a URL pattern skips rendering
    pattern_max_contradictions: int = 2  # a pattern contradicted this often stops skipping (until it expires)
    canary_rate: float = 0.05  # share of cache-approved captures rendered anyway, to keep evidence fresh

    # ---- rendering (adaptive renderer, see pagecapture.render) ----
    browser_ws: str | None = field(default_factory=lambda: os.environ.get("PAGECAPTURE_BROWSER_WS"))  # managed tier
    challenge_browser_ws: str | None = field(  # challenge-resolution tier (costlier; used only when requested)
        default_factory=lambda: os.environ.get("PAGECAPTURE_CHALLENGE_BROWSER_WS")
    )
    # residential exit country for the BrowserQL challenge tier (ISO code; our own fleet renders from Japan)
    proxy_country: str | None = field(default_factory=lambda: os.environ.get("PAGECAPTURE_PROXY_COUNTRY", "jp") or None)
    challenge_browser_proxied: bool = field(  # the challenge tier egresses through proxies: block pages are worth a try
        default_factory=lambda: os.environ.get("PAGECAPTURE_CHALLENGE_PROXIED", "").lower() in ("1", "true", "yes")
    )
    viewport_width: int = 1366
    viewport_height: int = 900
    block_resources: tuple[str, ...] = ("image", "media", "font")  # not needed for the HTML, halves the download
    max_transfer_mb: float = (
        20.0  # stop loading more once a render has transferred this much (proxied tiers bill per MB)
    )
    navigation_timeout_s: float = 30.0
    settle_quiet_s: float = 1.2  # content counts as settled after this long without growth
    settle_cap_s: float = 6.0
    boot_cap_s: float = 12.0  # extra wait for pages that are still nearly empty (apps still starting)
    scroll_max_steps: int = 25
    scroll_cap_s: float = 15.0
    final_read_s: float = 30.0  # reading the final DOM may wait this long for a busy page to answer
    render_cap_s: float = 60.0  # hard limit for one render, plus the tier's challenge wait
    challenge_wait_s: float = 5.0  # managed tier: a JS challenge sometimes clears by itself in a real browser
    challenge_resolution_wait_s: float = 60.0  # challenge tier: the provider's solver needs time (5-45 s seen)
