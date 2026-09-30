from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from websockets.asyncio.client import connect

from backend.proxy.adapters.cdp import WebSocketProviderSession
from backend.proxy.contracts import ProviderName, ResolvedSessionSettings, StolosioSession
from backend.proxy.transport.domain_blocking import apply_domain_blocking


def browserless_cloud_url(
    base_url: str,
    token: str,
    *,
    path: str,
    proxy_country: str,
    websocket: bool,
    timeout_ms: int | None = None,
) -> str:
    """A Browserless cloud route behind its residential proxy, pinned to one exit country."""
    parts = urlsplit(base_url)
    scheme = (
        {"https": "wss", "http": "ws"}.get(parts.scheme, parts.scheme)
        if websocket
        else parts.scheme
    )
    query = {"token": token, "proxy": "residential", "proxyCountry": proxy_country}
    if timeout_ms is not None:
        query["timeout"] = str(timeout_ms)
    return urlunsplit((scheme, parts.netloc, path, urlencode(query), ""))


@dataclass(frozen=True, slots=True)
class BrowserlessCloudAdapter:
    """Browserless's stealth CDP route. Cloud browsers sit outside Stolosio's egress firewall, so
    the network policy is applied in the browser itself."""

    base_url: str
    token: str
    proxy_country: str
    session_timeout_seconds: int
    provider: ProviderName = ProviderName.BROWSERLESS_CLOUD

    async def acquire(self, session: StolosioSession, settings: ResolvedSessionSettings):
        if not self.token:
            raise RuntimeError("Browserless cloud is not configured")
        endpoint = browserless_cloud_url(
            self.base_url,
            self.token,
            path="/stealth",
            proxy_country=settings.browserless.proxy_country or self.proxy_country,
            websocket=True,
            timeout_ms=self.session_timeout_seconds * 1000,
        )
        websocket = await connect(endpoint, max_size=None, proxy=None)
        return apply_domain_blocking(
            WebSocketProviderSession(
                self.provider,
                websocket,
                session_timeout_seconds=self.session_timeout_seconds,
            ),
            settings.blocked_domain_patterns,
        )
