"""Adaptive rendering: one generic algorithm that decides per page, while it renders, how long to wait and whether
to scroll. No per-site configuration.

1. Load until the HTML is parsed, then wait while *content* keeps growing (background network noise is ignored).
2. A page that is still nearly empty, has an empty app container, or still shows a text placeholder ("Loading...")
   in its main content, is probably an app still starting: keep waiting while content arrives (up to boot_cap_s).
3. Close an obvious consent dialog with its reject / necessary-only button.
4. Scroll a screen at a time to the bottom (the window, or the inner panel that scrolls). Stretches that add
   nothing are crossed faster, with a 10-screen-tall window (viewport-triggered lazy loading still fires).
   At the bottom, give late sections a moment; stop when nothing more arrives.
5. While loading placeholders are still visible, a short last wait (up to PENDING_CAP_S).

Content is collected across all snapshots: virtualized lists drop items that scroll out of view, so the final
DOM can hold less than the page showed. `Rendered.virtualized` flags when that happened.
"""

import asyncio
import base64
import gzip
import json
import logging
import re
import time
from dataclasses import dataclass, field

from ..api import Exclusion, excluded
from ..classify.rules import CHALLENGE_MARKUP, CHALLENGE_TITLES
from ..config import Settings
from . import scripts

log = logging.getLogger(__name__)

RENDERER_VERSION = "adaptive-5"  # bump when the algorithm changes (reported in capture evidence)


def content_lines(text: str) -> set[str]:
    """Visible text as a set of normalised lines (the unit content is measured in)."""
    out = set()
    for ln in text.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip().lower()
        if len(ln) >= 3 and not re.fullmatch(r"[\d\s.,:/%+-]+", ln):
            out.add(ln)
    return out


@dataclass
class Rendered:
    url: str
    final_url: str = ""
    status: int | None = None
    html: str = ""  # final DOM
    lines: set[str] = field(default_factory=set)  # every content line seen during the render
    final_lines: int = 0  # content lines in the final DOM
    items: int = 0  # distinct detail links seen
    seconds: float = 0.0
    requests: int = 0
    bytes: int = 0  # transferred over the network (encoded), what proxied tiers bill
    transfer_capped: bool = False  # hit max_transfer_mb: later requests were blocked
    early_dom: bool = False  # the page stopped answering: html is from early in the render
    steps: list[dict] = field(default_factory=list)  # what each step added (the log a learned policy trains on)
    final_state: dict = field(default_factory=dict)  # at the end: visible chars, empty app container, placeholders
    error: str | None = None
    excluded_url: str | None = None  # the page navigated (or redirected) to an excluded URL: nothing kept

    @property
    def virtualized(self) -> bool:
        """The page dropped content while scrolling: the final DOM holds noticeably less than was seen."""
        return self.final_lines < 0.8 * len(self.lines)


# Chrome URL-blocklist patterns per resource type (the blocklist matches URLs, not types)
_TYPE_PATTERNS = {
    "image": ("png", "jpg", "jpeg", "gif", "webp", "avif", "svg", "ico", "bmp"),
    "font": ("woff", "woff2", "ttf", "otf", "eot"),
    "media": ("mp4", "webm", "m3u8", "ts", "mp3", "m4a", "ogg", "mov"),
}


def blocked_url_patterns(types) -> list[str]:
    return [f"*.{ext}{tail}" for t in types for ext in _TYPE_PATTERNS.get(t, ()) for tail in ("", "?*")]


def exclusion_fetch_patterns(exclusions: tuple[Exclusion, ...]) -> list[str]:
    """CDP Fetch patterns that pause every request an exclusion may cover. They are a superset (a host matches as a
    prefix, a path as a string prefix): each paused request is then checked exactly and failed or continued, so
    requests outside the patterns are never intercepted."""
    out = set()
    for e in exclusions:
        if e.host == "*":
            path = e.path_prefix.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")
            out.add(f"*://*{path}*")
        elif e.host.startswith("*."):
            out |= {f"*://{e.host[2:]}*", f"*://*.{e.host[2:]}*"}
        else:
            out.add(f"*://{e.host}*")
    return sorted(out)


IDLE_QUIET_S = 0.3  # a page with no DOM changes and no requests in flight for this long is still
TICK_S = 0.1


class BrowserCapacity(Exception):
    """The browser fleet kept answering "busy" (503/429), or a provider refused for its plan's limits."""

    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class PageBusy(Exception):
    """The page didn't answer within BUSY_S: its main thread is busy (a heavy app on a slow browser)."""


BUSY_S = 8.0
PENDING_CAP_S = 3.0  # the last wait for visible loading placeholders
DRIVER_GONE = "Connection closed while reading from the driver"
NAVIGATED = re.compile(r"Execution context was destroyed|navigat|Cannot find context|Frame was detached", re.I)


class _Session:
    """Collects content across snapshots, logs what each step added, and waits on the page's own activity."""

    def __init__(self, page, t0: float, inflight=lambda: 0):
        self.page, self.t0, self.inflight = page, t0, inflight
        self.lines: set[str] = set()
        self.items: set[str] = set()
        self.steps: list[dict] = []
        self.mutations = -1  # DOM change count at the last snapshot
        self._calls = 0
        self.html = ""  # final DOM, taken at the end of the render (or early, see adaptive_render)
        self.early_dom = False  # the page stopped answering: html is the DOM from early in the render
        self.final_state: dict = {}
        self.text = ""
        # A snapshot forces a layout. On a busy page and a slow browser, back-to-back snapshots starve the page
        # itself, so the next one waits at least twice as long as the last one took.
        self.snap_cost = 0.0
        self.last_snap = 0.0

    async def eval(self, expr: str, arg=None, timeout_s: float = BUSY_S):
        """Evaluate a function expression in the page, bounded in time, with the result moved in chunks. A page that
        navigates meanwhile (a redirect, a challenge passing) is waited for and asked again."""
        for attempt in range(3):
            try:
                return await self._eval(expr, arg, timeout_s)
            except PageBusy:
                raise
            except Exception as e:
                if attempt == 2 or not NAVIGATED.search(str(e)):
                    raise
                try:
                    await self.page.wait_for_load_state("domcontentloaded", timeout=timeout_s * 1000)
                except Exception:
                    pass

    async def _eval(self, expr: str, arg, timeout_s: float):
        self._calls += 1
        call = self._calls

        async def run():
            first = await self.page.evaluate(scripts.chunked(expr), [arg, scripts.CHUNK, call])
            if first["none"]:
                return None
            parts, more, start = [first["head"]], first["more"], scripts.CHUNK
            while more:  # offsets in the page's own (UTF-16) units
                piece = await self.page.evaluate(scripts.SLICE, [call, start, scripts.CHUNK])
                if piece is None:
                    raise RuntimeError("Execution context was destroyed: result lost while reading it")
                parts.append(piece["part"])
                more, start = piece["more"], start + scripts.CHUNK
            data = "".join(parts)
            return json.loads(gzip.decompress(base64.b64decode(data)) if first["gz"] else data)

        try:
            return await asyncio.wait_for(run(), timeout_s)
        except TimeoutError:
            raise PageBusy(f"no answer in {timeout_s:.0f}s") from None

    async def bounded(self, call, timeout_s: float = BUSY_S):
        """Any other page call, bounded like eval: a page that doesn't answer is busy."""
        try:
            return await asyncio.wait_for(call, timeout_s)
        except TimeoutError:
            raise PageBusy(f"no answer in {timeout_s:.0f}s") from None

    def log(self, step: str) -> None:
        self.steps.append({"step": step, "t": round(time.perf_counter() - self.t0, 2), "new_lines": 0, "new_items": 0})

    async def snap(self, step: str) -> int:
        t = time.perf_counter()
        s = await self.eval(scripts.SNAPSHOT)
        self.last_snap = time.perf_counter()
        self.snap_cost = self.last_snap - t
        self.mutations = s["mut"]
        new_lines = content_lines("\n".join(s["lines"])) - self.lines
        new_items = set(s["items"]) - self.items
        self.lines |= new_lines
        self.items |= new_items
        self.steps.append(
            {
                "step": step,
                "t": round(time.perf_counter() - self.t0, 2),
                "new_lines": len(new_lines),
                "new_items": len(new_items),
            }
        )
        return len(new_lines) + 3 * len(new_items)

    def added_since(self, index: int) -> int:
        return sum(s["new_lines"] + 3 * s["new_items"] for s in self.steps[index:])

    async def settle(self, label: str, quiet_s: float, cap_s: float) -> int:
        """Wait while the page is still changing; return how much content was added.

        Settled when nothing changed in the DOM and no request was in flight for IDLE_QUIET_S (a still page), or
        when content stopped growing for quiet_s (a busy page whose trackers never go quiet). Snapshots are taken
        only when the DOM changed."""
        start = last_change = last_growth = time.perf_counter()
        before = len(self.steps)
        while time.perf_counter() - start < cap_s:
            await asyncio.sleep(TICK_S)
            now = time.perf_counter()
            if now - self.last_snap < 2 * self.snap_cost:
                continue
            if await self.eval(scripts.MUTATIONS) != self.mutations:
                last_change = now
                if await self.snap(label) > 0:
                    last_growth = now
            if now - last_change >= IDLE_QUIET_S and self.inflight() == 0:
                break
            if now - last_growth >= quiet_s:
                break
        return self.added_since(before)


async def wait_out_challenge(page, session: _Session, cap_s: float) -> None:
    """A bot challenge the browser may pass (or a provider solves): wait until the real page has replaced it, before
    any snapshot, so challenge text never counts as content. The challenge page navigates away when passed."""
    start, seen = time.perf_counter(), False
    while time.perf_counter() - start < cap_s:
        try:
            state = await page.evaluate(scripts.CHALLENGE_STATE, [list(CHALLENGE_TITLES), list(CHALLENGE_MARKUP)])
        except Exception:  # the context is torn down while the challenge navigates to the page
            state = {"challenged": True, "ready": False}
        if not state["challenged"] and state["ready"]:
            break
        seen = True
        await asyncio.sleep(0.5)
    if seen:
        session.log("challenge")


async def adaptive_render(
    page,
    url: str,
    s: Settings,
    session: _Session,
    challenge_wait_s: float = 0.0,
    navigate: bool = True,
    early_dom: bool = False,
) -> _Session:
    """navigate=False: the page is already there (handed over by a tier that unblocked it). early_dom: also keep the
    DOM right after the first snapshot, as a fallback for remote browsers whose pages may stop answering."""
    if navigate:
        await page.goto(url, wait_until="domcontentloaded", timeout=s.navigation_timeout_s * 1000)
    if challenge_wait_s:
        await wait_out_challenge(page, session, challenge_wait_s)
    try:
        await _explore(page, s, session, early_dom)
    except PageBusy as e:  # stop exploring and keep what the page has; its main thread may come back for the read
        session.log(f"page busy: stopped exploring ({e})")
    # the final DOM, taken while the page is known to respond (some remote browsers stop answering soon after)
    try:
        session.html = await session.eval(scripts.OUTER_HTML, timeout_s=s.final_read_s)
        session.final_state = await session.eval(scripts.PAGE_STATE, timeout_s=s.final_read_s)
        session.text = await session.eval(scripts.BODY_TEXT, timeout_s=s.final_read_s)
        session.early_dom = False
    except PageBusy:
        if not session.html:
            raise
        session.log("page stopped answering: kept the DOM from early in the render")
    return session


async def _explore(page, s: Settings, session: _Session, early_dom: bool) -> None:
    """Wait for the content to settle, give booting apps time, reject consent, scroll for lazy content."""
    await session.snap("parsed")
    if early_dom:
        session.html = await session.eval(scripts.OUTER_HTML)
        session.final_state = await session.eval(scripts.PAGE_STATE)
        session.early_dom = True
    await session.settle("settle", quiet_s=s.settle_quiet_s, cap_s=s.settle_cap_s)

    state = await session.eval(scripts.PAGE_STATE)
    boot = time.perf_counter()
    while booting(state) and time.perf_counter() - boot < s.boot_cap_s:
        added = await session.settle("boot", quiet_s=2.0, cap_s=4.0)
        state = await session.eval(scripts.PAGE_STATE)
        if added == 0 and state["chars"] >= 300 and not state["mount"] and not state["placeholders"]:
            break

    clicked = await session.eval(scripts.REJECT_CONSENT)
    if clicked:
        session.log(f"consent: {clicked}")
        await session.settle("after-consent", quiet_s=0.8, cap_s=3.0)

    target = await session.eval(scripts.SCROLL_STEP, 0)
    if target["scrollable"] or state["pending"]:
        start, grew, dry = time.perf_counter(), True, 0
        for i in range(s.scroll_max_steps):
            if time.perf_counter() - start > s.scroll_cap_s or not target["scrollable"]:
                break
            if dry == 2 and not target["inner"]:
                await session.bounded(
                    page.set_viewport_size({"width": s.viewport_width, "height": 10 * s.viewport_height})
                )
            await session.eval(scripts.SCROLL_STEP, 1)
            grew = (
                await session.settle(f"scroll {i + 1}", quiet_s=0.6 if grew else 0.3, cap_s=1.5 if grew else 0.8) >= 3
            )
            dry = 0 if grew else dry + 1
            target = await session.eval(scripts.SCROLL_STEP, 0)
            if target["at_bottom"] and not grew:
                late = await session.settle("bottom", quiet_s=1.0, cap_s=2.5)
                target = await session.eval(scripts.SCROLL_STEP, 0)
                if late < 3 and target["at_bottom"]:
                    break
        state = await session.eval(scripts.PAGE_STATE)
    pending_end = time.perf_counter() + PENDING_CAP_S
    while state["pending"] and (left := pending_end - time.perf_counter()) > 0:
        await session.settle("pending", quiet_s=1.0, cap_s=left)
        state = await session.eval(scripts.PAGE_STATE)


def booting(state: dict) -> bool:
    """An app still starting: little text, an empty app container, or main content still saying "Loading..."."""
    return state["chars"] < 1500 or state["mount"] or bool(state["placeholders"])


class Renderer:
    """Renders pages in a remote Chromium over CDP (a browser fleet such as browserless).

    async with Renderer(settings) as r:
        rendered = await r.render(url)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        endpoint: str | None = None,
        user_agent: str | None = "",
        challenge_wait_s: float | None = None,
        intercept: bool = True,
        early_dom: bool = False,
    ):
        """endpoint: the CDP endpoint for fresh browsers (default Settings.browser_ws; not needed when every render
        attaches to a handed-over browser). user_agent: default Settings.user_agent; None keeps the browser's own
        identity (a stealth provider's).
        challenge_wait_s: how long a challenge may take to clear (on top of the render cap). intercept: also block
        resources by type with request interception, which the URL blocklist misses some of but which stalls
        challenge solvers and can freeze a handed-over page. early_dom: see adaptive_render."""
        self.settings = settings or Settings()
        self.endpoint = endpoint or self.settings.browser_ws
        self.user_agent = self.settings.user_agent if user_agent == "" else user_agent
        self.challenge_wait_s = self.settings.challenge_wait_s if challenge_wait_s is None else challenge_wait_s
        self.intercept, self.early_dom = intercept, early_dom
        self._pw = None
        self._restart_lock = asyncio.Lock()

    async def __aenter__(self) -> "Renderer":
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._pw.stop()

    async def _connect(self, endpoint: str | None):
        """A fresh browser per render (no state shared between pages). Fleets answer 503 when busy: back off."""
        endpoint = endpoint or self.endpoint
        if not endpoint:
            raise ValueError("no browser endpoint: set PAGECAPTURE_BROWSER_WS or Settings.browser_ws")
        for attempt in range(6):
            try:
                return await self._pw.chromium.connect_over_cdp(endpoint)
            except Exception as e:
                if attempt == 5:
                    if re.search(r"\b(503|429)\b", str(e)):
                        raise BrowserCapacity(f"no browser capacity: {e}"[:300]) from e
                    raise
                await asyncio.sleep(min(2**attempt, 20))

    async def render(
        self,
        url: str,
        deadline_s: float | None = None,
        attach_ws: str | None = None,
        exclusions: tuple[Exclusion, ...] = (),
        endpoint: str | None = None,
    ) -> Rendered:
        """Render `url` in a fresh browser, or with `attach_ws`, continue on the page already open in that browser.
        No request to an excluded URL leaves the page, and a page that lands on one keeps nothing. `endpoint` picks
        the browser for this render (default: the renderer's endpoint).

        Playwright's driver process can die on a page (assertions on frames attaching mid-handover were seen), and
        every render sharing it fails with it: the driver is restarted and the render tried once more."""
        t0, driver = time.perf_counter(), self._pw
        try:
            result = await self._render(url, deadline_s, attach_ws, exclusions, endpoint)
            if not (result.error and DRIVER_GONE in result.error):
                return result
        except Exception as e:
            if DRIVER_GONE not in str(e):
                raise
        await self._restart_driver(driver)
        left = deadline_s - (time.perf_counter() - t0) if deadline_s else None
        return await self._render(url, left, attach_ws, exclusions, endpoint)

    async def _restart_driver(self, dead) -> None:
        async with self._restart_lock:
            if self._pw is not dead:  # a concurrent render already restarted it
                return
            try:
                await self._pw.stop()
            except Exception:
                pass
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()

    @staticmethod
    async def _guard(ctx, page, exclusions: tuple[Exclusion, ...], result: Rendered) -> None:
        """Fail every request to an excluded URL, redirect hops included, before it leaves the browser. Playwright's
        routing never sees redirect hops, and Chrome's URL blocklist set from this session didn't hold behind a CDP
        gateway; the Fetch domain, limited to candidate patterns, does both and pauses nothing else. A blocked
        main-frame document (Playwright reports no failure for a blocked redirect hop) marks the render excluded."""
        cdp = await ctx.new_cdp_session(page)
        main_frame = (await cdp.send("Page.getFrameTree"))["frameTree"]["frame"]["id"]
        decisions = set()  # in flight, held so none is collected mid-flight

        async def decide(event: dict) -> None:
            request_id = event["requestId"]
            try:
                if excluded(event["request"]["url"], exclusions):
                    if event.get("resourceType") == "Document" and event.get("frameId") == main_frame:
                        result.excluded_url = result.excluded_url or event["request"]["url"]
                    await cdp.send("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})
                else:
                    await cdp.send("Fetch.continueRequest", {"requestId": request_id})
            except Exception:
                pass  # the page or its session is closing

        def on_paused(event: dict) -> None:
            task = asyncio.ensure_future(decide(event))
            decisions.add(task)
            task.add_done_callback(decisions.discard)

        cdp.on("Fetch.requestPaused", on_paused)
        patterns = [{"urlPattern": p, "requestStage": "Request"} for p in exclusion_fetch_patterns(exclusions)]
        await cdp.send("Fetch.enable", {"patterns": patterns})

    async def _render(
        self,
        url: str,
        deadline_s: float | None,
        attach_ws: str | None,
        exclusions: tuple[Exclusion, ...],
        endpoint: str | None = None,
    ) -> Rendered:
        s = self.settings
        cap_s = s.render_cap_s + self.challenge_wait_s
        cap_s = min(cap_s, deadline_s) if deadline_s else cap_s
        result = Rendered(url=url)
        t0 = time.perf_counter()
        browser = await (self._pw.chromium.connect_over_cdp(attach_ws) if attach_ws else self._connect(endpoint))
        try:
            if attach_ws:
                ctx = browser.contexts[0]
                page = next((p for p in ctx.pages if p.url not in ("", "about:blank")), None) or ctx.pages[0]
                await page.set_viewport_size({"width": s.viewport_width, "height": s.viewport_height})
                result.status = await page.evaluate(
                    "() => (performance.getEntriesByType('navigation')[0] || {}).responseStatus || null"
                )
            else:
                identity = {"user_agent": self.user_agent} if self.user_agent else {}
                ctx = await browser.new_context(
                    viewport={"width": s.viewport_width, "height": s.viewport_height},
                    locale="en-US",
                    service_workers="block",
                    **identity,
                )
                page = await ctx.new_page()
            await page.add_init_script(scripts.MUTATION_COUNTER)
            if attach_ws:
                await page.evaluate(scripts.MUTATION_COUNTER)  # the current document is already loaded
            if not self.intercept:
                # A tier whose solver runs inside this session (plain-CDP challenge tier): interception would stall
                # it, so heavy resources go through Chrome's URL blocklist, which doesn't pause requests, with exact
                # bytes on the wire and a cap. That needs CDP network events, which flood the Playwright driver on a
                # heavy page (seen crashing it at 9 MB); every other tier intercepts and reads the page's own count.
                cdp = await ctx.new_cdp_session(page)
                await cdp.send("Network.enable")
                if s.block_resources:
                    await cdp.send("Network.setBlockedURLs", {"urls": blocked_url_patterns(s.block_resources)})

                def on_loaded(event):
                    result.bytes += int(event.get("encodedDataLength", 0))
                    if result.bytes > s.max_transfer_mb * 1e6 and not result.transfer_capped:
                        result.transfer_capped = True  # stop paying for more: the page keeps what it has
                        asyncio.ensure_future(cdp.send("Network.setBlockedURLs", {"urls": ["*"]}))

                cdp.on("Network.loadingFinished", on_loaded)
            if exclusions:
                await self._guard(ctx, page, exclusions, result)
            pending = set()  # requests in flight, to tell a still page from a loading one
            page.on("request", lambda req: pending.add(req))
            page.on("requestfinished", lambda req: pending.discard(req))

            def on_failed(req):
                pending.discard(req)
                if req.is_navigation_request() and req.frame == page.main_frame and excluded(req.url, exclusions):
                    result.excluded_url = result.excluded_url or req.url

            page.on("requestfailed", on_failed)
            routed = self.intercept and bool(s.block_resources or exclusions)
            if routed:
                blocked = set(s.block_resources)

                async def route(r):  # a page closing mid-request must not leave an unhandled error in the driver
                    try:
                        refuse = r.request.resource_type in blocked or excluded(r.request.url, exclusions)
                        await (r.abort("blockedbyclient") if refuse else r.continue_())
                    except Exception:
                        pass

                await page.route("**/*", route)

            def on_response(resp):
                result.requests += 1
                if resp.request.is_navigation_request() and resp.request.frame == page.main_frame:
                    result.status = resp.status

            page.on("response", on_response)

            # created here so that a render cut off at the cap still keeps what it collected
            session = _Session(page, time.perf_counter(), lambda: len(pending))
            try:
                await asyncio.wait_for(
                    adaptive_render(
                        page, url, s, session, self.challenge_wait_s, navigate=not attach_ws, early_dom=self.early_dom
                    ),
                    timeout=cap_s,
                )
            except Exception as e:  # keep what was captured before a timeout or a page error
                result.error = repr(e)[:300]
            result.final_url = page.url
            if excluded(result.final_url, exclusions):  # e.g. a handed-over page that redirected before the handover
                result.excluded_url = result.excluded_url or result.final_url
            failed_navigation = result.final_url.startswith("chrome-error://")  # Chrome's own error page
            if result.excluded_url:
                result.error = f"navigated to an excluded URL: {result.excluded_url}"
            elif failed_navigation:
                code = re.search(r"ERR_[A-Z0-9_]+", session.html or session.text or "")
                result.error = f"navigation failed: {code.group(0) if code else 'network error in the browser'}"

            async def read(expr: str, timeout_s: float = 15.0):
                """Reads after the render are bounded: a hung page must not hold the capture (or the session)."""
                t = time.perf_counter()
                try:
                    return await session.eval(expr, timeout_s=timeout_s)
                except Exception as e:
                    log.debug("read %s failed after %.1fs: %r", expr[:40], time.perf_counter() - t, e)
                    result.error = result.error or f"reading the page failed: {e!r}"[:300]
                    return None

            if not (failed_navigation or result.excluded_url):  # otherwise nothing of the site's to keep
                # serialised in the page itself: Playwright's content() can hang on a browser handed over mid-session
                if session.html:
                    result.html, result.final_state = session.html, session.final_state
                    result.early_dom = session.early_dom
                if self.intercept and result.final_state:  # no CDP byte count on this tier: the page's own
                    result.bytes = int(result.final_state.get("bytes") or 0)
                else:  # cut off before the end: read what the page has now
                    result.html = await read(scripts.OUTER_HTML) or ""
                    result.final_state = await read(scripts.PAGE_STATE, 5.0) or {}
                text = session.text or await read(scripts.BODY_TEXT, 5.0) or ""
                result.final_lines = len(content_lines(text))
                result.lines = session.lines | content_lines(text)
            result.items, result.steps = len(session.items), session.steps
            try:
                if routed:
                    await asyncio.wait_for(page.unroute_all(behavior="ignoreErrors"), 5.0)
                await asyncio.wait_for(ctx.close(), 5.0)
            except Exception:
                pass
        finally:
            try:
                await asyncio.wait_for(browser.close(), 5.0)
            except Exception:
                pass
        result.seconds = round(time.perf_counter() - t0, 2)
        return result
