"""Stolosio's fetcher: the egress proxy's own error answers are not the site's."""

import socket

import httpx
import pytest
from pagecapture import FetchError, HostNotFound, Settings

from backend.proxy.capture.fetcher import StolosioFetcher


class Squid(httpx.AsyncBaseTransport):
    """A plain-HTTP fetch through squid: the site redirects to a host squid can't resolve."""

    async def handle_async_request(self, request):
        if request.url.host == "site.example.test":
            return httpx.Response(
                301, headers={"location": "http://gone.example.test/"}, request=request
            )
        return httpx.Response(
            503,
            headers={"x-squid-error": "ERR_DNS_FAIL 0", "content-type": "text/html"},
            content=b"<html>Unable to determine IP address</html>",
            request=request,
        )


def resolver(monkeypatch, answer):
    asked = []

    def getaddrinfo(host, *args, **kwargs):
        asked.append(host)
        if isinstance(answer, int):
            raise socket.gaierror(answer, "resolver says no")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return asked


async def fetch():
    fetcher = StolosioFetcher(Settings(), transport=Squid())
    try:
        return await fetcher.fetch("http://site.example.test/", 10)
    finally:
        await fetcher.close()


@pytest.mark.asyncio
async def test_a_proxy_dns_failure_for_a_missing_host_is_host_not_found(monkeypatch) -> None:
    asked = resolver(monkeypatch, socket.EAI_NONAME)
    with pytest.raises(HostNotFound) as error:
        await fetch()
    assert error.value.host == "gone.example.test"  # the failed redirect hop's host
    assert asked == ["gone.example.test."]


@pytest.mark.asyncio
async def test_a_proxy_dns_failure_the_resolver_does_not_confirm_stays_transient(
    monkeypatch,
) -> None:
    resolver(monkeypatch, socket.EAI_AGAIN)
    with pytest.raises(FetchError) as error:
        await fetch()
    assert not isinstance(error.value, HostNotFound)
    assert "ERR_DNS_FAIL" in str(error.value)
