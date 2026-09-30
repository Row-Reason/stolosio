"""The bot identity, and replaying stored responses (snapshots make labels and benchmarks reproducible)."""

import base64
import gzip
import json
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.structures import CaseInsensitiveDict

# One identity for the plain fetch and the managed render. Browser tokens pass naive user-agent checks; the bot still
# identifies itself (same format as Googlebot). The challenge tier keeps its provider's own browser identity.
BOT_INFO_URL = "https://github.com/elei-io/stolosio"
USER_AGENT = (
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; "
    f"compatible; StolosioBot/0.1; +{BOT_INFO_URL}) Chrome/150.0.0.0 Safari/537.36"
)


@dataclass
class Fetched:
    url: str
    response: requests.Response | None  # None when there was no HTTP response at all
    error: str | None


def make_response(
    status: int, url: str, headers, body: bytes = b"", history=(), encoding: str | None = None
) -> requests.Response:
    """A response in the `requests` interface the classifier reads, from any source (live fetch, render, snapshot)."""
    r = requests.Response()
    r.status_code, r.url, r._content = status, url, body
    r.headers = CaseInsensitiveDict(headers)
    r.history = list(history)
    if encoding:
        r.encoding = encoding
    return r


def from_record(rec: dict) -> Fetched:
    if "error" in rec:
        return Fetched(rec["url"], None, rec["error"])
    history = [make_response(h["status"], h["url"], {"Location": h["location"]}) for h in rec["history"]]
    return Fetched(
        rec["url"],
        make_response(
            rec["status"], rec["final_url"], rec["headers"], base64.b64decode(rec["body"]), history, rec["encoding"]
        ),
        None,
    )


def load_snapshot(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt") as f:
        return {rec["url"]: rec for rec in map(json.loads, f)}
