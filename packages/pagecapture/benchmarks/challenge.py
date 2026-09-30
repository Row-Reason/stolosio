"""Benchmark the challenge-resolution tier on bot-protected pages.

    uv run python benchmarks/challenge.py run data/challenge_benchmark_urls.tsv results/challenge.jsonl
    uv run python benchmarks/challenge.py report results/challenge.jsonl

Each URL gets a full production capture with resolve_bot_challenges=True (PAGECAPTURE_CHALLENGE_BROWSER_WS), so
the result is what a caller would get: plain HTTP first, the managed fleet where HTTP isn't challenged today, and the
challenge tier only where the ladder sends it. Pages were labelled as bot-protected at some point; many are not
challenged today, which the report shows separately. Runs are appended and resumable.
"""

import argparse
import asyncio
import json
import statistics
from collections import Counter

from _harness import quantile, run_jsonl

from pagecapture import CaptureRequest, CaptureService
from pagecapture.config import Settings
from pagecapture.document import Document
from pagecapture.fetch import make_response


def text_chars(body: bytes) -> int:
    return len(
        Document(
            "https://x/", make_response(200, "https://x/", {"Content-Type": "text/html; charset=utf-8"}, body)
        ).text
    )


async def capture_one(service: CaptureService, url: str, kind: str) -> dict:
    result = await service.capture(CaptureRequest(url=url, resolve_bot_challenges=True))
    out = result.to_json(include_body=False)
    tiers = [a["tier"] for a in out["evidence"]["attempts"]]
    challenge = next((a for a in out["evidence"]["attempts"] if a["tier"] == "challenge_resolution"), None)
    rec = {
        "url": url,
        "kind": kind,
        "outcome": out["outcome"],
        "failure": (out.get("failure") or {}).get("code"),
        "message": ((out.get("failure") or {}).get("message") or "")[:200],
        "tiers": tiers,
        "representation": (out.get("document") or {}).get("representation"),
        "cost": out["evidence"]["cost"],
        "attempts": out["evidence"]["attempts"],
    }
    if challenge:
        rec["challenge_seconds"] = round(challenge["duration_ms"] / 1000, 1)
        rec["unblock"] = next(
            (s["step"] for s in challenge.get("steps") or [] if s["step"].startswith("unblock")), None
        )
    if result.document is not None and result.outcome == "captured":
        rec["text_chars"] = text_chars(result.document.body)
    return rec


async def run(rows: list[tuple[str, str]], out: str, parallel: int) -> None:
    service = CaptureService(Settings())
    await run_jsonl(
        rows,
        out,
        lambda row: capture_one(service, *row),
        key=lambda row: row[0],
        parallel=parallel,
        describe=lambda r: (
            f"{r['url'][:60]:60} {r.get('kind', ''):10} {r.get('outcome', 'error'):8} "
            f"{r.get('failure') or ''} {'>'.join(r.get('tiers', []))} {r.get('challenge_seconds', '')}"
        ),
    )
    await service.close()


def report(path: str) -> None:
    recs = [json.loads(line) for line in open(path)]
    errors = [r for r in recs if "error" in r]
    recs = [r for r in recs if "error" not in r]
    print(f"{len(recs)} captures ({len(errors)} harness errors)\n")
    used = [r for r in recs if "challenge_resolution" in r["tiers"]]
    free = [r for r in recs if "challenge_resolution" not in r["tiers"]]
    print(
        f"not challenged today (no paid tier used): {len(free)}  "
        + ", ".join(f"{k}: {v}" for k, v in Counter(r["failure"] or r["outcome"] for r in free).most_common())
    )
    print(f"sent to the challenge tier: {len(used)}\n")
    for kind in ("challenge", "block_page"):
        rows = [r for r in used if r["kind"] == kind]
        if not rows:
            continue
        ok = [r for r in rows if r["outcome"] == "captured"]
        print(f"{kind}: {len(ok)}/{len(rows)} captured ({len(ok) / len(rows):.0%})")
        print(
            "  outcomes: "
            + ", ".join(
                f"{k}: {v}"
                for k, v in Counter(
                    (r["failure"] or r["outcome"]) + (f" ({r['representation']})" if r["representation"] else "")
                    for r in rows
                ).most_common()
            )
        )
        print(
            "  unblock: "
            + ", ".join(f"{k}: {v}" for k, v in Counter(r.get("unblock") or "-" for r in rows).most_common())
        )
    if used:
        secs = sorted(r["challenge_seconds"] for r in used if "challenge_seconds" in r)
        mb = sorted(r["cost"]["bytes"] / 1e6 for r in used)
        print(
            f"\nchallenge tier seconds: median {statistics.median(secs):.0f}, p90 {quantile(secs, 0.9):.0f}, max {secs[-1]:.0f}"
        )
        print(
            f"transferred MB (measured by the renderer; excludes the unblock step's own load): "
            f"median {statistics.median(mb):.2f}, p90 {quantile(mb, 0.9):.2f}, max {mb[-1]:.2f}"
        )
        chars = sorted(r.get("text_chars", 0) for r in used if r["outcome"] == "captured")
        if chars:
            print(f"captured text chars: median {statistics.median(chars):.0f}, min {chars[0]}")
    failed = [r for r in used if r["outcome"] != "captured"]
    if failed:
        print("\nfailed on the challenge tier:")
        for r in failed:
            print(
                f"  {r['kind']:10} {r['failure']:20} {r.get('unblock') or '-':32} {r['url'][:70]}  {r['message'][:80]}"
            )
    for r in errors:
        print(f"  harness error: {r['url'][:70]} {r['error'][:100]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("urls")
    r.add_argument("out")
    r.add_argument("--parallel", type=int, default=4)
    p = sub.add_parser("report")
    p.add_argument("results")
    args = parser.parse_args()
    if args.command == "run":
        rows = [
            tuple(line.split("\t")) for line in open(args.urls).read().splitlines() if line and not line.startswith("#")
        ]
        asyncio.run(run(rows, args.out, args.parallel))
    else:
        report(args.results)


if __name__ == "__main__":
    main()
