import httpx
from pagecapture import EgressError, HttpxFetcher


class StolosioFetcher(HttpxFetcher):
    """Plain HTTP through Stolosio's egress proxy only: page acquisition never inherits the API
    process's own network access. The proxy's own answers (a firewall-denied destination, an
    unreachable site) are not the site's; HttpxFetcher reports one as a missing host only when a
    resolver confirms the host doesn't exist."""

    def check_hop(self, response: httpx.Response) -> None:
        # An origin spoofing this header can only make its own fetch fail.
        error = response.headers.get("x-squid-error", "")
        if error.startswith("ERR_"):
            code = error.split()[0][:64]
            raise EgressError(
                f"the egress proxy denied or could not reach the destination ({code})",
                response.request.url.raw_host.decode("ascii"),
            )
