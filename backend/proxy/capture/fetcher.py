import httpx
from pagecapture import FetchError, HttpxFetcher


class StolosioFetcher(HttpxFetcher):
    """Plain HTTP through Stolosio's egress proxy only: page acquisition never inherits the API
    process's own network access. The proxy's own answers (a firewall-denied destination, an
    unreachable site) are not the site's."""

    def check_hop(self, response: httpx.Response) -> None:
        # An origin spoofing this header can only make its own fetch fail.
        if response.headers.get("x-squid-error", "").startswith("ERR_"):
            raise FetchError("the egress proxy denied or could not reach the destination")
