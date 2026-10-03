"""Text loading placeholders ("Loading...") in main content keep the adaptive renderer waiting, within its caps.

Runs the renderer against fixture pages in a local headless Chromium; skipped where none is installed."""

import asyncio
import time

import pytest

from pagecapture import Settings
from pagecapture.render import scripts
from pagecapture.render.adaptive import PENDING_CAP_S, _Session, adaptive_render

URL = "http://fixture.test/page"
# chrome text well over the 1500 characters that otherwise end the boot wait
CHROME = "<header><nav>" + " ".join(f"<a href='/c/{i}'>Country {i} English</a>" for i in range(120)) + "</nav></header>"
SETTINGS = Settings(
    browser_ws=None, settle_cap_s=2.0, boot_cap_s=4.0, scroll_max_steps=3, scroll_cap_s=2.0, final_read_s=5.0
)


async def _with_page(html: str, use):
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as e:  # no local Chromium (CI installs no browsers)
            pytest.skip(f"no local Chromium: {e}"[:200])
        try:
            page = await browser.new_page(viewport={"width": SETTINGS.viewport_width, "height": 900})
            await page.add_init_script(scripts.MUTATION_COUNTER)
            await page.route(
                "**/*", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
            )
            return await use(page)
        finally:
            await browser.close()


def render(html: str) -> tuple[_Session, float]:
    async def use(page):
        t0 = time.perf_counter()
        session = await adaptive_render(page, URL, SETTINGS, _Session(page, t0))
        return session, time.perf_counter() - t0

    return asyncio.run(_with_page(html, use))


def page_state(body: str) -> dict:
    async def use(page):
        await page.goto(URL)
        return await page.evaluate(scripts.PAGE_STATE)

    return asyncio.run(_with_page(f"<!doctype html><html><body>{body}</body></html>", use))


def test_placeholder_replaced_after_a_delay_is_waited_for():
    html = f"""<!doctype html><html><body>{CHROME}
      <main><h1>Loading...</h1><div id="product"></div></main>
      <script>setTimeout(() => {{
        document.querySelector('h1').textContent = 'Series 7 chair';
        document.querySelector('#product').innerHTML = '<p>Designed by Arne Jacobsen in 1955, stackable.</p>';
      }}, 2500);</script></body></html>"""
    session, _ = render(html)
    assert "Series 7 chair" in session.html and "Arne Jacobsen" in session.html
    assert "Loading..." not in session.html
    assert any(s["step"] == "boot" for s in session.steps)
    assert session.final_state["placeholders"] == 0 and session.final_state["pending"] == 0


def test_permanent_placeholder_finishes_within_the_caps():
    html = f"<!doctype html><html><body>{CHROME}<main><h1>Loading…</h1></main></body></html>"
    session, seconds = render(html)
    assert session.final_state["placeholders"] == 1 and session.final_state["pending"] == 1
    # boot wait (cap + one settle overrun), short scroll, last pending wait, and slack for a slow machine
    assert SETTINGS.boot_cap_s <= seconds < SETTINGS.boot_cap_s + 4.0 + SETTINGS.scroll_cap_s + PENDING_CAP_S + 3.0


def test_prose_mentioning_loading_is_not_a_placeholder():
    html = f"""<!doctype html><html><body>{CHROME}<main>
      <h1>Loading docks of Yokohama</h1>
      <p>The ship was <em>loading</em> all night.</p>
      <p>Loading... is what the screen said, the subject of this essay about slow pages.</p>
      </main></body></html>"""
    session, seconds = render(html)
    assert session.final_state["placeholders"] == 0 and session.final_state["pending"] == 0
    assert not any(s["step"] in ("boot", "pending") for s in session.steps)
    assert seconds < SETTINGS.boot_cap_s


@pytest.mark.parametrize(
    "body, expected",
    [
        ("<main><div>Loading</div></main>", 1),
        ("<main><p><span>Loading</span> <span>...</span></p></main>", 1),  # split across inline elements
        ("<main><div class='msg'><span>Ladataan…</span></div></main>", 1),
        ("<h1>読み込み中</h1>", 1),
        ("<div role='main'><p>Chargement en cours...</p></div>", 1),
        ("<main><div style='display:none'>Loading...</div></main>", 0),  # hidden
        ("<nav><span>Loading...</span></nav><main><p>A product page.</p></main>", 0),  # chrome, not content
        ("<header>Loading...</header><div id='page'><section><p>Loading...</p></section></div>", 1),  # no main
        ("<main><p>Loading the truck takes an hour.</p></main>", 0),
    ],
)
def test_page_state_counts_visible_text_placeholders_in_content(body, expected):
    state = page_state(body)
    assert state["placeholders"] == expected
    assert state["pending"] == expected
