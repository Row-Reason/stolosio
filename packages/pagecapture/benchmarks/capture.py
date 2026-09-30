"""End-to-end check of the capture service on labelled URLs: outcome agreement with the labels, and where time goes.

    uv run python benchmarks/capture.py run data/labels.csv results/capture.jsonl [--sample 300]
    uv run python benchmarks/capture.py run data/labels.csv results/deployed.jsonl --endpoint http://stolosio:8411
    uv run python benchmarks/capture.py report results/capture.jsonl

Each URL gets a full production capture (plain HTTP, classification, managed render, comparison) with an empty
method cache, so every HTML page is rendered (the worst case for time), and resolve_bot_challenges=False (the
paid tier is measured by benchmarks/challenge.py). With --endpoint, captures go through a deployed service instead:
its own fleet, egress and shared method cache, so pages it has seen before may skip the render. The expected outcome
comes from the audited label:

- a reason that ends a capture (404, login wall, bot challenge, ...) -> that failure;
- otherwise (usable, or content missing that a browser adds) -> captured.

Labels describe the response when it was labelled, so part of the disagreement is the web having changed since.
"""

import argparse
import asyncio
import csv
import json
import random
import statistics
from collections import Counter

from _harness import Endpoint, quantile, run_jsonl

from pagecapture import CaptureRequest, CaptureService
from pagecapture.cache import MemoryMethodCache
from pagecapture.config import Settings
from pagecapture.labels import REASONS, RENDER_NEED

# label reason -> failure codes that count as agreeing
EXPECTED = {
    "unreachable": {"unreachable"},
    "bot_challenge": {"bot_challenge", "bot_blocked"},
    "rate_limited": {"rate_limited"},
    "geo_blocked": {"geo_blocked"},
    "unsupported_browser": {"unsupported_browser"},
    "auth": {"access_denied"},
    "paywall": {"paywall"},
    "parked": {"parked"},
    "gone": {"gone", "not_found"},
    "not_found": {"not_found", "gone"},
    "client_error": {"access_denied", "request_rejected"},
    "server_error": {"website_error"},
    "interstitial": {"interstitial"},
}


def expected(row: dict) -> str:
    """The label's primary blocking reason, or "captured"."""
    for reason in REASONS:
        if row.get(f"_{reason}") == "true" and reason not in RENDER_NEED and reason != "payload_mismatch":
            return reason
    return "captured"


async def run(rows: list[dict], out: str, parallel: int, endpoint: str | None) -> None:
    service = Endpoint(endpoint) if endpoint else CaptureService(Settings(), cache=MemoryMethodCache())

    async def one(row: dict) -> dict:
        if isinstance(service, Endpoint):
            res, _, wall = await service.capture(row["url"], resolve_bot_challenges=False)
        else:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            res = (await service.capture(CaptureRequest(url=row["url"]))).to_json(include_body=False)
            wall = loop.time() - t0
        return {
            "url": row["url"],
            "expected": expected(row),
            "outcome": res["outcome"],
            "failure": (res.get("failure") or {}).get("code"),
            "representation": (res.get("document") or {}).get("representation"),
            "attempts": [
                {
                    k: a.get(k)
                    for k in (
                        "path",
                        "tier",
                        "status_code",
                        "duration_ms",
                        "decision",
                        "decision_reason",
                        "comparison",
                        "notes",
                    )
                }
                for a in res["evidence"]["attempts"]
            ],
            "cost": res["evidence"]["cost"],
            "wall_s": round(wall, 2),
        }

    await run_jsonl(
        rows,
        out,
        one,
        key=lambda row: row["url"],
        parallel=parallel,
        describe=lambda r: (
            f"{r['url'][:60]:60} {r.get('expected', ''):14} "
            f"{r.get('failure') or r.get('outcome', 'error')}  {r.get('wall_s', '')}s"
        ),
    )
    await service.close()


def report(path: str) -> None:
    recs = [json.loads(line) for line in open(path)]
    errors = [r for r in recs if "error" in r]
    recs = [r for r in recs if "error" not in r]
    n = len(recs)
    if not n:
        print("no captures")
        return
    print(f"{n} captures ({len(errors)} harness errors)\n")

    def agrees(r):
        if r["expected"] == "captured":
            return r["outcome"] == "captured"
        return r["outcome"] == "failed" and r["failure"] in EXPECTED.get(r["expected"], set())

    outcome_ok = sum((r["expected"] == "captured") == (r["outcome"] == "captured") for r in recs)
    print(f"captured-vs-failed agrees with the label: {outcome_ok}/{n} ({outcome_ok / n:.1%})")
    print(
        f"exact agreement (and the same failure reason): {sum(map(agrees, recs))}/{n} ({sum(map(agrees, recs)) / n:.1%})"
    )
    exp_cap = [r for r in recs if r["expected"] == "captured"]
    exp_fail = [r for r in recs if r["expected"] != "captured"]
    print(f"  labelled usable/renderable: {sum(r['outcome'] == 'captured' for r in exp_cap)}/{len(exp_cap)} captured")
    print(
        f"  labelled blocked/broken:    {sum(r['outcome'] == 'failed' for r in exp_fail)}/{len(exp_fail)} failed, "
        f"{sum(map(agrees, exp_fail))} with the labelled reason"
    )
    print("\nlabel -> result where they differ:")
    for (e, got), k in Counter(
        (r["expected"], r["failure"] or r["outcome"]) for r in recs if not agrees(r)
    ).most_common(15):
        print(f"  {k:4}  {e:16} -> {got}")

    print(
        "\ncaptured documents: "
        + ", ".join(
            f"{k}: {v}"
            for k, v in Counter(r["representation"] for r in recs if r["outcome"] == "captured").most_common()
        )
    )
    cov = [a["comparison"]["http_coverage"] for r in recs for a in r["attempts"] if a.get("comparison")]
    if cov:
        print(
            f"HTTP coverage of the render: {sum(c >= 0.95 for c in cov)}/{len(cov)} pages ≥95% (HTTP would have been enough)"
        )

    print("\ntime (seconds):")
    wall = [r["wall_s"] for r in recs]
    http = [r["attempts"][0]["duration_ms"] / 1000 for r in recs if r["attempts"]]
    browser = [
        a["duration_ms"] / 1000 for r in recs for a in r["attempts"] if a["path"] == "browser" and a["duration_ms"]
    ]
    for name, xs in (("whole capture", wall), ("plain HTTP fetch", http), ("browser render", browser)):
        if xs:
            print(
                f"  {name:18} median {statistics.median(xs):5.1f}  p90 {quantile(xs, 0.9):5.1f}  max {max(xs):5.1f}  (n={len(xs)})"
            )
    over = [r for r in recs if r["wall_s"] > 60]
    for r in sorted(over, key=lambda r: -r["wall_s"])[:8]:
        print(f"  slow: {r['wall_s']:5.0f}s {r['url'][:70]}  {r['failure'] or r['outcome']}")
    for r in errors[:10]:
        print(f"  harness error: {r['url'][:70]} {r['error'][:100]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("labels")
    r.add_argument("out")
    r.add_argument("--sample", type=int, default=300)
    r.add_argument("--parallel", type=int, default=4)
    r.add_argument("--endpoint", help="a deployed capture service's base URL (default: in-process)")
    p = sub.add_parser("report")
    p.add_argument("results")
    args = parser.parse_args()
    if args.command == "run":
        rows = list(csv.DictReader(open(args.labels)))
        random.Random(11).shuffle(rows)
        asyncio.run(run(rows[: args.sample], args.out, args.parallel, args.endpoint))
    else:
        report(args.results)


if __name__ == "__main__":
    main()
