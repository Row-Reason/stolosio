"""A main-frame navigation the site refuses is a failed navigation, never page content.

When page.goto raises net::ERR_CONNECTION_REFUSED, page.url still reads about:blank: Chrome commits its error page
(chrome-error://chromewebdata/, "This site can't be reached") a moment later. The renderer must not read that page
as the site's (a ~165-character page is "empty", which turned a refused browser into incomplete_content); the capture
fails as transient `unreachable`. Fake pages reproduce the timing deterministically; a local Chromium, where one is
installed, checks the real browser."""

import asyncio
import json
import socket

import pytest
from playwright.async_api import Error as PlaywrightError

from pagecapture import CaptureRequest, CaptureService, HttpResponse, Settings
from pagecapture.adapters import CdpBrowserTier
from pagecapture.cache import MemoryMethodCache
from pagecapture.render import Renderer, scripts

URL = "https://web.archive.org/web/20250917085820id_/https://job-boards.greenhouse.io/carbon"
ARTICLE = (
    "<html><head><title>A long story</title></head><body><main><h1>Headline</h1>"
    + "".join(f"<p>Paragraph {i} with enough words to count as real server rendered content.</p>" for i in range(60))
    + "</main></body></html>"
)
# Chrome's error page for a refused connection, as a full (non-headless-shell) Chrome shows it
ERROR_TEXT = (
    "This site can’t be reached\nweb.archive.org refused to connect.\nTry:\n\nChecking the connection\n"
    "Checking the proxy and the firewall\n{code}\nReload\nDetails"
)
SMALL = "<html><head><title>Telegram</title></head><body><p>Log in to Telegram by QR code</p></body></html>"
SETTINGS = Settings(
    browser_ws="ws://fleet", challenge_browser_ws=None, canary_rate=0.0, challenge_wait_s=0.0, boot_cap_s=0.5
)
NAMES = {
    scripts.chunked(getattr(scripts, n)): n
    for n in ("SNAPSHOT", "MUTATIONS", "PAGE_STATE", "REJECT_CONSENT", "SCROLL_STEP", "OUTER_HTML", "BODY_TEXT")
}


class FakeRequest:
    def __init__(self, page, url, failure=None):
        self.url, self.frame, self.failure = url, page.main_frame, failure

    def is_navigation_request(self):
        return True


class FakeResponse:
    def __init__(self, request, status):
        self.request, self.status = request, status


class FakePage:
    """A page whose navigation either loads `html` or fails with `net_error`, raising from goto before Chrome commits
    its error page (as Chrome does). `event=False` drops the requestfailed event, leaving only goto's exception."""

    def __init__(self, html=SMALL, net_error=None, event=True):
        self.html, self.net_error, self.event = html, net_error, event
        self.main_frame, self.handlers, self._url = object(), {}, "about:blank"

    @property
    def url(self):
        return self._url

    def on(self, name, handler):
        self.handlers.setdefault(name, []).append(handler)

    def fire(self, name, arg):
        for handler in self.handlers.get(name, []):
            handler(arg)

    async def add_init_script(self, script):
        pass

    async def route(self, pattern, handler):
        pass

    async def unroute_all(self, behavior=None):
        pass

    async def wait_for_load_state(self, state, **options):
        pass

    async def goto(self, url, **options):
        request = FakeRequest(self, url)
        self.fire("request", request)
        if self.net_error:
            request.failure = f"net::{self.net_error}"
            if self.event:
                self.fire("requestfailed", request)
            self.committed = "chrome-error://chromewebdata/"  # committed a moment after goto raised
            raise PlaywrightError(f'Page.goto: net::{self.net_error} at {url}\nCall log:\n  - navigating to "{url}"')
        self.fire("response", FakeResponse(request, 200))
        self.fire("requestfinished", request)
        self._url = url

    def _text(self):
        if self.net_error:
            return ERROR_TEXT.format(code=self.net_error)
        return self.html.split("<body>")[1].split("</body>")[0].replace("<p>", "").replace("</p>", "")

    async def evaluate(self, expression, arg=None):
        if self.net_error:  # the next call into the page lands on Chrome's error page
            self._url = self.committed
        html = f"<html><body>{self._text()}</body></html>" if self.net_error else self.html
        text = self._text()
        name = NAMES[expression]
        value = {
            "SNAPSHOT": {"mut": 1, "lines": text.split("\n"), "items": []},
            "MUTATIONS": 1,
            "PAGE_STATE": {"chars": len(text), "mount": False, "pending": 0, "placeholders": 0, "bytes": len(html)},
            "REJECT_CONSENT": None,
            "SCROLL_STEP": {"scrollable": False, "inner": False, "at_bottom": True},
            "OUTER_HTML": html,
            "BODY_TEXT": text,
        }[name]
        if value is None:
            return {"none": True, "head": "", "more": False, "gz": False}
        return {"none": False, "head": json.dumps(value), "more": False, "gz": False}


class FakeBrowser:
    def __init__(self, page):
        self.page = page

    async def new_context(self, **kwargs):
        return self

    async def new_page(self):
        return self.page

    async def close(self):
        pass


class FakePlaywright:
    def __init__(self, page):
        self.chromium = self
        self.page = page

    async def connect_over_cdp(self, endpoint):
        return FakeBrowser(self.page)


class FakeTier:
    tier, paid, proxied = "managed", False, False

    def __init__(self, page):
        self.renderer = Renderer(SETTINGS)
        self.renderer._pw = FakePlaywright(page)

    async def render(self, url, deadline_s, exclusions=()):
        return await self.renderer.render(url, deadline_s=deadline_s, exclusions=exclusions)


class FakeFetcher:
    """Plain HTTP (through the fetch proxy) got the page, as in production."""

    def __init__(self, body=ARTICLE):
        self.body = body

    async def fetch(self, url, timeout_s, exclusions=(), accept=None):
        return HttpResponse(url, url, 200, [("Content-Type", "text/html; charset=utf-8")], self.body.encode(), [], 12.0)


def capture(managed, fetcher=None):
    service = CaptureService(SETTINGS, fetcher=fetcher or FakeFetcher(), managed=managed, cache=MemoryMethodCache())

    async def run():
        try:
            return await service.capture(CaptureRequest(url=URL))
        finally:
            await service.close()

    return asyncio.run(run())


@pytest.mark.parametrize("event", [True, False], ids=["requestfailed-event", "goto-error-only"])
def test_a_refused_navigation_fails_before_chrome_commits_its_error_page(event):
    page = FakePage(net_error="ERR_CONNECTION_REFUSED", event=event)
    rendered = asyncio.run(FakeTier(page).render(URL, deadline_s=30))
    assert rendered.error == "navigation failed: ERR_CONNECTION_REFUSED"
    assert rendered.html == "" and not rendered.lines and rendered.final_state == {}  # the error page is not read


def test_a_refused_browser_is_unreachable_not_incomplete_content():
    r = capture(FakeTier(FakePage(net_error="ERR_CONNECTION_REFUSED")))
    assert r.outcome == "failed"
    assert (r.failure.code, r.failure.category, r.failure.transient) == ("unreachable", "network", True)
    assert r.failure.message == "the site refused the browser's connection (net::ERR_CONNECTION_REFUSED)"
    assert r.document.body == ARTICLE.encode()  # plain HTML kept as failure evidence, never promoted
    assert r.evidence.attempts[-1].decision == "fail"


def test_a_failed_proxy_tunnel_stays_browser_unavailable():
    r = capture(FakeTier(FakePage(net_error="ERR_TUNNEL_CONNECTION_FAILED")))
    assert (r.failure.code, r.failure.category) == ("browser_unavailable", "gateway")
    assert "proxy couldn't reach the site" in r.failure.message


def test_a_small_page_that_loads_is_still_read_and_assessed():
    page = FakePage(html=SMALL)
    rendered = asyncio.run(FakeTier(page).render(URL, deadline_s=30))
    assert rendered.error is None and rendered.html == SMALL and rendered.final_url == URL and rendered.lines
    # an empty plain page and a small render: the render is the capture (unchanged by navigation-failure detection)
    r = capture(FakeTier(FakePage(html=SMALL)), FakeFetcher("<html><body><div id='x'></div></body></html>"))
    assert r.outcome == "captured" and r.document.representation == "rendered_html"
    # usable plain HTML and a render under 200 characters stays unverified: incomplete_content
    r = capture(FakeTier(FakePage(html=SMALL)))
    assert r.failure.code == "incomplete_content" and "came out empty" in r.failure.message


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_real_browser_refused_by_a_closed_port_is_unreachable():
    """A local Chromium over CDP, like a browser fleet; skipped where none is installed."""
    from playwright.async_api import async_playwright

    closed, cdp = _free_port(), _free_port()

    async def run():
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(args=[f"--remote-debugging-port={cdp}"])
            except Exception as e:  # no local Chromium (CI installs no browsers)
                pytest.skip(f"no local Chromium: {e}"[:200])
            settings = Settings(browser_ws=None, challenge_browser_ws=None, canary_rate=0.0)
            service = CaptureService(
                settings,
                fetcher=FakeFetcher(),
                managed=CdpBrowserTier(f"http://127.0.0.1:{cdp}", "managed", False, settings),
                cache=MemoryMethodCache(),
            )
            try:
                return await service.capture(CaptureRequest(url=f"http://127.0.0.1:{closed}/page"))
            finally:
                await service.close()
                await browser.close()

    r = asyncio.run(run())
    assert (r.failure.code, r.failure.transient) == ("unreachable", True)
    assert "net::ERR_CONNECTION_REFUSED" in r.failure.message
