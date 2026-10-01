"""BrowserQL challenge-tier failures: provider refusals are capacity, outages stay browser_unavailable, and neither
the token nor a URL's query reaches logs or failure messages."""

import asyncio
import logging

import httpx
import pytest

from pagecapture.adapters import BqlBrowserTier, ChallengeNotPassed
from pagecapture.render import BrowserCapacity

TOKEN = "s3cr3t-token-value"


def tier(handler) -> BqlBrowserTier:
    t = BqlBrowserTier(f"https://bql.test/stealth/bql?token={TOKEN}&proxy=residential")
    t._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return t


def unblock(t: BqlBrowserTier):
    return asyncio.run(t._unblock("https://site.test/page?session=abc", 30))


def respond(status, body=None, headers=None, text=None):
    def handler(request):
        if text is not None:
            return httpx.Response(status, text=text, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    return handler


@pytest.mark.parametrize(
    ("status", "headers", "retry_after"),
    [
        (429, {"Retry-After": "12"}, 12.0),
        (429, None, 30.0),
        (402, None, 3600.0),
    ],
)
def test_refusal_statuses_are_capacity_with_retry_after(status, headers, retry_after, caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(BrowserCapacity) as e:
        unblock(tier(respond(status, headers=headers, text=f"Too many requests for token={TOKEN}")))
    assert e.value.retry_after_seconds == retry_after
    assert f"HTTP {status}" in caplog.text
    assert TOKEN not in caplog.text and TOKEN not in str(e.value)


@pytest.mark.parametrize(
    ("message", "retry_after"),
    [
        ("Concurrency limit reached for your plan", 30.0),
        ("Your account is out of units: upgrade to continue", 3600.0),
    ],
)
def test_browserql_errors_naming_a_limit_are_capacity(message, retry_after):
    with pytest.raises(BrowserCapacity) as e:
        unblock(tier(respond(200, {"errors": [{"message": message}], "data": None})))
    assert e.value.retry_after_seconds == retry_after


@pytest.mark.parametrize(
    "handler",
    [
        respond(500, text="Internal Server Error"),
        respond(503, text="<html>Bad gateway</html>"),
        respond(401, text="Unauthorized"),
        respond(200, {"errors": [{"message": "Navigation failed because browser has disconnected"}]}),
        respond(200, text="not json"),
    ],
)
def test_outages_and_faults_stay_runtime_errors(handler):
    with pytest.raises(RuntimeError) as e:
        unblock(tier(handler))
    assert not isinstance(e.value, BrowserCapacity)


def test_a_failed_request_never_leaks_the_token(caplog):
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as e:
        unblock(tier(handler))
    assert TOKEN not in str(e.value) and TOKEN not in caplog.text
    assert "BrowserQL request failed" in caplog.text


def test_summaries_are_bounded_and_drop_url_queries(caplog):
    body = "error at https://site.test/page?session=abc " + "x" * 5000
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as e:
        unblock(tier(respond(500, text=body)))
    assert "session=abc" not in str(e.value) and "session=abc" not in caplog.text
    assert len(str(e.value)) < 300


def test_captcha_timeout_is_still_a_challenge_not_passed():
    with pytest.raises(ChallengeNotPassed):
        unblock(tier(respond(200, {"errors": [{"message": "Captcha solving timed out after 60000 ms"}]})))
