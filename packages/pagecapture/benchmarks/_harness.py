"""Shared benchmark plumbing: resumable JSONL runs and quantiles."""

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Iterable


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
