"""The two things a host service provides: a way to fetch over plain HTTP, and browsers per tier.

stolosio plugs in its own implementations (its proxied, policy-checked fetch; its managed fleet and its
challenge-resolution provider). The defaults here keep the package usable on its own: httpx for HTTP and any CDP
endpoint (e.g. browserless) for browsers.
"""

import asyncio
import email.utils
import time
from dataclasses import dataclass, field, replace
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx
import requests

from .api import Exclusion, Redirect, Tier, accepts, excluded
from .config import Settings
from .fetch import make_response
from .render import Rendered, Renderer

ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


def media_type(headers: list[tuple[str, str]]) -> tuple[str | None, str | None]:
    """(media type, charset) from Content-Type; (None, None) when the response didn't say."""
    value = next((v for k, v in headers if k.lower() == "content-type"), "") or ""
    parts = [p.strip() for p in value.split(";")]
    charset = next((p.split("=", 1)[1].strip('"') for p in parts[1:] if p.lower().startswith("charset=")), None)
    return (parts[0].lower() or None), charset


@dataclass
class HttpResponse:
    """A plain HTTP fetch result, as any fetcher reports it."""

    requested_url: str
    final_url: str
    status_code: int
    headers: list[tuple[str, str]]  # received order, duplicates kept
    body: bytes
    redirects: list[Redirect] = field(default_factory=list)
    elapsed_ms: float = 0.0
    truncated: bool = False  # the body was longer than the size cap: only its start was read

    def header(self, name: str) -> str | None:
        return next((v for k, v in self.headers if k.lower() == name.lower()), None)

    def as_requests(self) -> requests.Response:
        """The classifier reads responses through the `requests` interface."""
        history = [make_response(h.status, h.url, {"Location": h.location}) for h in self.redirects]
        return make_response(self.status_code, self.final_url, dict(self.headers), self.body, history)

    def retry_after_seconds(self) -> float | None:
        value = self.header("retry-after")
        if not value:
            return None
        if value.strip().isdigit():
            return float(value.strip())
        try:
            when = email.utils.parsedate_to_datetime(value)
            return max(0.0, when.timestamp() - time.time())
        except (TypeError, ValueError):
            return None


class ChallengeNotPassed(Exception):
    """A challenge tier tried and the bot protection held (its solver gave up, or the site refused the connection)."""


class FetchError(Exception):
    """No HTTP response at all (DNS, connection, TLS, timeout)."""


class ExcludedUrl(Exception):
    """A redirect led to a URL the request excludes (or the host's own network policy blocks)."""

    def __init__(self, url: str):
        super().__init__(f"redirected to an excluded URL: {url}")
        self.url = url


class UnsupportedMediaType(Exception):
    """The response's media type is outside the request's accept list. The body was not read."""

    def __init__(self, response: HttpResponse, media_type: str):
        super().__init__(f"media type {media_type} is not accepted")
        self.response, self.media_type = response, media_type


class Fetcher(Protocol):
    async def fetch(
        self, url: str, timeout_s: float, exclusions: tuple[Exclusion, ...] = (), accept: tuple[str, ...] | None = None
    ) -> HttpResponse:
        """Fetch over plain HTTP following redirects. Raise FetchError when there is no response, ExcludedUrl when a
        hop is excluded, and UnsupportedMediaType, before reading the body, when a successful response declares a media
        type that isn't accepted (error responses are read: their status and page say what went wrong)."""


class BrowserTier(Protocol):
    tier: Tier  # managed rendering, local resolution, or paid challenge resolution
    paid: bool
    proxied: bool  # egresses through proxies (another IP identity): block pages may let it through

    async def render(self, url: str, deadline_s: float, exclusions: tuple[Exclusion, ...] = ()) -> Rendered:
        """Render the page adaptively (see pagecapture.render) within the deadline, never requesting an excluded
        URL."""


class _SharedPool(httpx.AsyncBaseTransport):
    """One connection pool for every fetch, while cookies stay per fetch (each fetch has its own client, and a
    client closes its transport when it closes)."""

    def __init__(self, transport: httpx.AsyncBaseTransport):
        self._transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        pass


class HttpxFetcher:
    """Default fetcher: httpx with the bot identity, every redirect hop checked against the exclusions, the declared
    media type checked before the body is read, and the body read up to the size cap. `proxy` sends every fetch
    through an egress proxy."""

    def __init__(
        self,
        settings: Settings | None = None,
        proxy: str | None = None,
        pool_size: int = 64,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.s = settings or Settings()
        self._pool = transport or httpx.AsyncHTTPTransport(
            proxy=proxy, limits=httpx.Limits(max_connections=pool_size, max_keepalive_connections=pool_size)
        )
        self._headers = {"User-Agent": self.s.user_agent, "Accept": ACCEPT_HEADER, "Accept-Language": "en-US,en;q=0.9"}

    def check_hop(self, response: httpx.Response) -> None:
        """Every response on the way, redirects included, before it's followed or read. A host raises FetchError here
        for answers that come from its egress rather than the site (stolosio: its proxy's own error pages)."""

    async def fetch(
        self, url: str, timeout_s: float, exclusions: tuple[Exclusion, ...] = (), accept: tuple[str, ...] | None = None
    ) -> HttpResponse:
        async def check(request: httpx.Request) -> None:
            hop = str(request.url)
            if excluded(hop, exclusions):
                raise ExcludedUrl(hop)

        async def check_response(response: httpx.Response) -> None:
            self.check_hop(response)

        start = time.perf_counter()
        client = httpx.AsyncClient(
            transport=_SharedPool(self._pool),
            headers=self._headers,
            trust_env=False,
            follow_redirects=True,
            max_redirects=10,
            timeout=min(timeout_s, 30),
            event_hooks={"request": [check], "response": [check_response]},
        )
        try:
            async with asyncio.timeout(timeout_s), client, client.stream("GET", url) as r:
                headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in r.headers.raw]
                redirects = [Redirect(h.status_code, str(h.url), h.headers.get("location", "")) for h in r.history]
                response = HttpResponse(url, str(r.url), r.status_code, headers, b"", redirects)
                declared, _ = media_type(headers)
                if 200 <= r.status_code < 300 and declared and not accepts(accept, declared):
                    response.elapsed_ms = (time.perf_counter() - start) * 1000
                    raise UnsupportedMediaType(response, declared)
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > self.s.http_max_response_bytes:
                        response.truncated = True
                        break
                response.body = bytes(body[: self.s.http_max_response_bytes])
        except TimeoutError as e:
            raise FetchError(f"no complete response within {timeout_s:.0f} s") from e
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise FetchError(f"{type(e).__name__}: {e}"[:300]) from e
        response.elapsed_ms = (time.perf_counter() - start) * 1000
        return response

    async def close(self) -> None:
        await self._pool.aclose()


class CdpBrowserTier:
    """A browser tier behind a CDP WebSocket endpoint (browserless-compatible), rendered adaptively."""

    def __init__(
        self,
        ws_url: str,
        tier: Tier = "managed",
        paid: bool = False,
        settings: Settings | None = None,
        proxied: bool = False,
    ):
        self.tier, self.paid, self.proxied = tier, paid, proxied
        # The managed tier identifies as the bot. The challenge tier keeps the provider's own browser identity (its
        # stealth fingerprint is what gets it through; a bot UA would give it away), waits for the provider's solver,
        # and uses no request interception, which stalls solvers.
        s = settings or Settings()
        solving = tier == "challenge_resolution"
        local = tier == "local_resolution"
        if local:
            s = replace(
                s, block_resources=(), render_cap_s=s.local_resolution_cap_s - s.local_resolution_progress_wait_s
            )
        self._renderer = Renderer(
            s,
            endpoint=ws_url,
            user_agent=None if solving or local else s.user_agent,
            challenge_wait_s=(
                s.local_resolution_wait_s if local else s.challenge_resolution_wait_s if solving else s.challenge_wait_s
            ),
            intercept=not (solving or local),
            challenge_progress_wait_s=s.local_resolution_progress_wait_s if local else None,
        )
        self._started = False

    async def render(self, url: str, deadline_s: float, exclusions: tuple[Exclusion, ...] = ()) -> Rendered:
        if not self._started:
            await self._renderer.__aenter__()
            self._started = True
        return await self._renderer.render(url, deadline_s=deadline_s, exclusions=exclusions)

    async def close(self) -> None:
        if self._started:
            await self._renderer.__aexit__(None, None, None)
            self._started = False


UNBLOCK = """mutation Unblock($url: String!, $navigationTimeout: Float, $solveTimeout: Float) {
  reject(type: [%s]) { enabled }
  goto(url: $url, waitUntil: domContentLoaded, timeout: $navigationTimeout) { status }
  solve(timeout: $solveTimeout) { found solved time }
  reconnect(timeout: 60000) { browserWSEndpoint }
}"""


class BqlBrowserTier:
    """Browserless BrowserQL (`https://…/stealth/bql?token=…&proxy=residential`): Browserless navigates and solves any
    challenge on its side (seconds, where a solver behind a plain CDP session took 30-130 s or froze), then hands the
    unblocked browser over CDP, where the adaptive renderer continues on the same page without navigating again.

    Heavy resources are blocked by BrowserQL's `reject` while Browserless loads the page, and by the renderer's
    request interception after the handover (`reject` ends there). The solver has finished by then, so interception
    can't stall it, and the renderer needs no CDP network events (which flood the Playwright driver on heavy pages).
    The residential exit is pinned to Settings.proxy_country unless the URL names one."""

    def __init__(
        self,
        bql_url: str,
        tier: Tier = "challenge_resolution",
        paid: bool = True,
        settings: Settings | None = None,
        proxied: bool = False,
    ):
        self.tier, self.paid, self.proxied = tier, paid, proxied
        s0 = settings or Settings()
        if s0.proxy_country and "proxyCountry=" not in bql_url:
            bql_url += ("&" if "?" in bql_url else "?") + f"proxyCountry={s0.proxy_country}"
        self.bql_url = bql_url
        self._token = parse_qs(urlparse(bql_url).query).get("token", [""])[0]
        # a far-away provider through a residential proxy: slower navigation, and pages that may stop answering
        s = settings or Settings()
        self.s = replace(s, navigation_timeout_s=max(s.navigation_timeout_s, 60.0))
        self._query = UNBLOCK % ", ".join(self.s.block_resources)
        self._renderer = Renderer(self.s, user_agent=None, challenge_wait_s=self.s.challenge_wait_s, early_dom=True)
        self._http = httpx.AsyncClient(trust_env=False)
        self._started = False

    async def _unblock(self, url: str, timeout_s: float) -> dict:
        variables = {
            "url": url,
            "navigationTimeout": self.s.navigation_timeout_s * 1000,
            "solveTimeout": self.s.challenge_resolution_wait_s * 1000,
        }
        r = await self._http.post(self.bql_url, json={"query": self._query, "variables": variables}, timeout=timeout_s)
        if r.status_code != 200:
            raise RuntimeError(f"BrowserQL HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        if body.get("errors"):
            message = f"BrowserQL: {body['errors'][0].get('message', body['errors'][0])}"[:300]
            if "captcha solving timed out" in message.lower():
                raise ChallengeNotPassed(message)
            raise RuntimeError(message)
        return body["data"]

    async def render(self, url: str, deadline_s: float, exclusions: tuple[Exclusion, ...] = ()) -> Rendered:
        """BrowserQL navigates on Browserless's side, so exclusions apply from the handover on (and to the page it
        landed on); redirect hops inside the unblock itself can't be checked."""
        if not self._started:
            await self._renderer.__aenter__()
            self._started = True
        start = time.perf_counter()
        rendered = await self._render_once(url, deadline_s, exclusions)
        left = deadline_s - (time.perf_counter() - start)
        if rendered.final_url.startswith("chrome-error://") and left > 30:
            # the navigation failed at the network level (often the proxy's exit IP): once more, with a new session
            retry = await self._render_once(url, left, exclusions)
            retry.seconds = round(retry.seconds + rendered.seconds, 2)
            retry.steps.insert(
                0, {"step": "retry: the first navigation failed", "t": rendered.seconds, "new_lines": 0, "new_items": 0}
            )
            rendered = retry
        return rendered

    async def _render_once(self, url: str, deadline_s: float, exclusions: tuple[Exclusion, ...]) -> Rendered:
        t0 = time.perf_counter()
        data = await self._unblock(url, max(deadline_s - 5, 10))
        unblock_s = time.perf_counter() - t0
        endpoint = data["reconnect"]["browserWSEndpoint"]
        if self._token and "token=" not in endpoint:
            endpoint += ("&" if "?" in endpoint else "?") + "token=" + self._token
        rendered = await self._renderer.render(
            url, deadline_s=deadline_s - unblock_s, attach_ws=endpoint, exclusions=exclusions
        )
        solve = data.get("solve") or {}
        rendered.steps.insert(
            0,
            {
                "step": "unblock (solved)"
                if solve.get("solved")
                else "unblock (challenge not solved)"
                if solve.get("found")
                else "unblock",
                "t": round(unblock_s, 2),
                "new_lines": 0,
                "new_items": 0,
            },
        )
        rendered.seconds = round(rendered.seconds + unblock_s, 2)
        return rendered

    async def close(self) -> None:
        await self._http.aclose()
        if self._started:
            await self._renderer.__aexit__(None, None, None)
            self._started = False
