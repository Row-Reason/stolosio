"""Shared benchmark plumbing: resumable JSONL runs, quantiles and captures through a deployed endpoint."""

import asyncio
import base64
import json
import sys
import time
from collections.abc import Awaitable, Callable, Iterable

import httpx


def done_keys(out: str, key: Callable[[dict], object]) -> set:
    """Keys of the records already in `out` (runs are appended and resumable)."""
    try:
        return {key(json.loads(line)) for line in open(out)}
    except FileNotFoundError:
        return set()


async def run_jsonl(
    items: Iterable,
    out: str,
    work: Callable[[object], Awaitable[dict]],
    *,
    key: Callable[[object], object] = lambda item: item,
    record_key: Callable[[dict], object] = lambda rec: rec["url"],
    describe: Callable[[dict], str] = lambda rec: rec.get("url", ""),
    parallel: int = 4,
) -> None:
    """Run `work` on every item not yet in `out`, `parallel` at a time, appending one JSON record per item.
    A failing item is recorded as {"url", "error"} (key(item) must then be the URL) instead of stopping the run."""
    done = done_keys(out, record_key)
    todo = [i for i in items if key(i) not in done]
    print(f"{len(done)} done, {len(todo)} to go", file=sys.stderr)
    sem = asyncio.Semaphore(parallel)
    with open(out, "a") as sink:

        async def one(item):
            async with sem:
                try:
                    rec = await work(item)
                except Exception as e:
                    rec = {"url": key(item), "error": repr(e)[:300]}
                sink.write(json.dumps(rec, ensure_ascii=False) + "\n")
                sink.flush()
                print(f"  {describe(rec)}", file=sys.stderr, flush=True)

        await asyncio.gather(*(one(i) for i in todo))


def quantile(xs, q: float) -> float:
    """The q-quantile (nearest rank below) of xs; 0 when empty."""
    xs = sorted(xs)
    return xs[int(q * (len(xs) - 1))] if xs else 0.0


class Endpoint:
    """A deployed capture service (POST {base}/v1/capture), for benchmarking what callers actually get."""

    def __init__(self, base: str) -> None:
        self._client = httpx.AsyncClient(base_url=base.rstrip("/"), timeout=httpx.Timeout(300, connect=10))

    async def capture(self, url: str, **fields) -> tuple[dict, bytes | None, float]:
        """The capture's response JSON (without the body), its body, and the seconds the answering request took.
        A 503 capacity refusal is waited out (Retry-After) and not counted: it measures the fleet, not the capture."""
        while True:
            started = time.monotonic()
            response = await self._client.post("/v1/capture", json={"url": url, **fields})
            if response.status_code == 503:
                await asyncio.sleep(float(response.headers.get("Retry-After", 5)))
                continue
            response.raise_for_status()
            out = response.json()
            document = out.get("document") or {}
            encoded = document.pop("body_base64", None)
            return out, base64.b64decode(encoded) if encoded is not None else None, time.monotonic() - started

    async def close(self) -> None:
        await self._client.aclose()
