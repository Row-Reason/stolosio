"""The default fetcher: redirect hops checked against exclusions, accept before the body, size cap, no shared
cookies."""

import asyncio

import httpx
import pytest

from pagecapture import ExcludedUrl, Exclusion, FetchError, HttpxFetcher, Settings, UnsupportedMediaType

HTML = [("content-type", "text/html; charset=utf-8")]


class Site(httpx.AsyncBaseTransport):
    """Routes by path; records every request it served."""

    def __init__(self, routes):
        self.routes, self.seen, self.streams = routes, [], []

    async def handle_async_request(self, request):
        self.seen.append(request)
        status, headers, body = self.routes[request.url.path]
        self.streams.append(Stream(body))
        return httpx.Response(status, headers=headers, stream=self.streams[-1], request=request)


class Stream(httpx.AsyncByteStream):
    def __init__(self, body: bytes):
        self.body, self.read = body, 0

    async def __aiter__(self):
        for i in range(0, len(self.body), 1024):
            self.read += 1024
            yield self.body[i : i + 1024]


def fetch(site, url="https://example.test/", settings=None, **kwargs):
    async def run():
        fetcher = HttpxFetcher(settings or Settings(), transport=site)
        return await fetcher.fetch(url, 10, **kwargs)

    return asyncio.run(run())


def test_redirects_are_followed_with_ordered_headers_and_the_bot_identity():
    site = Site(
        {
            "/": (301, [("location", "/final")], b""),
            "/final": (200, [*HTML, ("set-cookie", "a=1"), ("set-cookie", "b=2")], b"<html>ok</html>"),
        }
    )
    r = fetch(site)
    assert r.final_url == "https://example.test/final" and r.body == b"<html>ok</html>"
    assert [h for h in r.headers if h[0] == "set-cookie"] == [("set-cookie", "a=1"), ("set-cookie", "b=2")]
    assert [(x.status, x.location) for x in r.redirects] == [(301, "/final")]
    assert "StolosioBot" in site.seen[0].headers["user-agent"]


def test_a_redirect_to_an_excluded_url_is_never_requested():
    site = Site({"/": (302, [("location", "/private/x")], b""), "/private/x": (200, HTML, b"secret")})
    with pytest.raises(ExcludedUrl) as e:
        fetch(site, exclusions=(Exclusion("example.test", "/private"),))
    assert e.value.url == "https://example.test/private/x"
    assert [str(r.url) for r in site.seen] == ["https://example.test/"]


def test_an_unaccepted_media_type_fails_before_the_body_is_read():
    site = Site({"/": (200, [("content-type", "application/pdf")], b"%PDF" * 100_000)})
    with pytest.raises(UnsupportedMediaType) as e:
        fetch(site, accept=("text/html",))
    assert e.value.media_type == "application/pdf" and e.value.response.body == b""
    assert site.streams[0].read == 0


def test_error_responses_are_read_whatever_their_media_type():
    site = Site({"/": (429, [("content-type", "application/json"), ("retry-after", "30")], b'{"error": 1}')})
    r = fetch(site, accept=("text/html",))
    assert r.status_code == 429 and r.body == b'{"error": 1}' and r.retry_after_seconds() == 30


def test_the_body_stops_at_the_size_cap():
    site = Site({"/": (200, HTML, b"x" * 50_000)})
    r = fetch(site, settings=Settings(http_max_response_bytes=10_000))
    assert r.truncated and len(r.body) == 10_000


def test_cookies_do_not_leak_between_fetches():
    site = Site({"/": (200, [*HTML, ("set-cookie", "session=1")], b"<html></html>")})

    async def twice():
        fetcher = HttpxFetcher(Settings(), transport=site)
        await fetcher.fetch("https://example.test/", 10)
        await fetcher.fetch("https://example.test/", 10)

    asyncio.run(twice())
    assert "cookie" not in site.seen[1].headers


def test_no_response_is_a_fetch_error():
    class Down(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("refused", request=request)

    with pytest.raises(FetchError):
        fetch(Down())
