"""Calibrate the HTTP-vs-render comparison (pagecapture.compare) that decides when plain HTTP is enough.

    uv run python benchmarks/comparison.py run data/comparison_calibration_urls.txt results/comparison.jsonl
    uv run python benchmarks/comparison.py report results/comparison.jsonl

Per URL, with the production fetcher and renderer: the raw HTTP body and two independent renders. Stored (gzipped)
so the comparison can be re-tuned later without re-crawling. Runs are appended and resumable.

The report:
- noise floor: how much two renders of the same page disagree;
- truth: content both renders saw (volatile text drops out); "plain HTTP truly holds it" = its coverage of that;
- production's estimate: coverage of ONE render by the plain response, as the service computes it;
- for each threshold: how often the estimate approves a page whose plain response truly misses content (lenient:
  loses content) or rejects one that holds it all (strict: a needless render), and the share of pages that could
  skip rendering.
"""

import argparse
import asyncio
import base64
import gzip
import json
import statistics
from collections import Counter

from _harness import quantile, run_jsonl

from pagecapture.adapters import FetchError, HttpxFetcher
from pagecapture.classify.rules import CHALLENGE_TEXT
from pagecapture.compare import coverage, http_windows, rendered_shingles
from pagecapture.config import Settings
from pagecapture.document import Document
from pagecapture.fetch import make_response
from pagecapture.render import RENDERER_VERSION, Renderer


def pack(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode()


def unpack(text: str) -> bytes:
    return gzip.decompress(base64.b64decode(text))


FETCHER = HttpxFetcher(Settings())


async def capture_one(url: str, renderer: Renderer) -> dict:
    rec = {"url": url, "renderer": RENDERER_VERSION}
    try:
        http = await FETCHER.fetch(url, 20)
    except FetchError as e:
        return {**rec, "http_error": str(e)}
    ct = next((v for k, v in http.headers if k.lower() == "content-type"), "")
    rec.update(
        status=http.status_code,
        content_type=ct,
        final_url=http.final_url,
        http_html=pack(Document(url, http.as_requests()).html.encode()) if "html" in ct.lower() or not ct else None,
    )
    if http.status_code != 200 or rec["http_html"] is None:
        return rec  # nothing to compare: blocked, broken or not HTML
    rec["renders"] = []
    for _ in range(2):
        r = await renderer.render(url)
        rec["renders"].append(
            {
                "lines": sorted(r.lines),
                "html": pack(r.html.encode()),
                "seconds": r.seconds,
                "status": r.status,
                "error": r.error,
                "final_state": r.final_state,
                "items": r.items,
            }
        )
    return rec


async def run(urls: list[str], out: str, parallel: int) -> None:
    async with Renderer(Settings()) as renderer:
        await run_jsonl(
            urls,
            out,
            lambda url: capture_one(url, renderer),
            parallel=parallel,
            describe=lambda r: f"{r['url'][:70]:70} {r.get('status', '-')} renders={len(r.get('renders', []))}",
        )


def pct(x: float) -> str:
    return f"{x:5.1%}"


def report(path: str) -> None:
    rows, skipped = [], Counter()
    for rec in map(json.loads, open(path)):
        if "error" in rec or "http_error" in rec:
            skipped["no response / harness error"] += 1
            continue
        if "renders" not in rec:
            skipped[f"not comparable (status {rec.get('status')}, {rec.get('content_type', '')[:20]})"] += 1
            continue
        r1, r2 = rec["renders"]
        lines1, lines2 = set(r1["lines"]), set(r2["lines"])
        if any(c in line.lower() for line in lines1 | lines2 for c in CHALLENGE_TEXT):
            skipped["a render met a bot challenge"] += 1
            continue
        if len(lines1) < 3 or len(lines2) < 3:
            skipped["a render came out empty"] += 1
            continue
        # the plain response exactly as production reads it (compare.http_windows over the parsed page)
        page = Document(
            rec["url"],
            make_response(200, rec["url"], {"Content-Type": "text/html; charset=utf-8"}, unpack(rec["http_html"])),
        )
        windows = http_windows(page)
        s1, s2 = rendered_shingles(lines1), rendered_shingles(lines2)
        stable = s1 & s2
        if not stable:
            skipped["renders share no content"] += 1
            continue
        est1, est2 = coverage(windows, lines1), coverage(windows, lines2)
        truth = len(stable & windows) / len(stable)  # share of the content both renders saw
        rows.append(
            {
                "url": rec["url"],
                "est": est1,
                "est2": est2,
                "truth": truth,
                "noise": 1 - len(s1 & s2) / max(len(s1 | s2), 1),
                "seconds": (r1["seconds"] + r2["seconds"]) / 2,
            }
        )
    n = len(rows)
    print(f"{n} comparable pages; not used: " + ", ".join(f"{k}: {v}" for k, v in skipped.most_common()))
    if not n:
        return
    noise = sorted(r["noise"] for r in rows)
    print(
        f"\nnoise floor (share of content that differs between two renders of the same page):"
        f"\n  median {pct(statistics.median(noise))}, p75 {pct(quantile(noise, 0.75))}, p90 {pct(quantile(noise, 0.9))}"
    )
    agree = sum((r["est"] >= 0.95) == (r["est2"] >= 0.95) for r in rows)
    print(f"  the two renders give the same verdict at 95%: {agree}/{n} ({agree / n:.0%})")

    truths = sorted(r["truth"] for r in rows)
    print("\nhow much of the stable content plain HTTP truly holds:")
    for lo, hi in ((0.98, 2), (0.95, 0.98), (0.9, 0.95), (0.8, 0.9), (0.5, 0.8), (0, 0.5)):
        k = sum(lo <= t < hi for t in truths)
        print(
            f"  {'≥' + format(lo, '.0%') if hi > 1 else format(lo, '.0%') + '–' + format(hi, '.0%'):>9}: {k:4} ({k / n:.0%})"
        )

    for truth_bar in (0.95, 0.98):
        print(
            f"\nplain HTTP 'truly enough' = holds ≥{truth_bar:.0%} of the stable content "
            f"({sum(r['truth'] >= truth_bar for r in rows)}/{n} pages)"
        )
        print(
            f"  {'threshold':>9} {'skip share':>10} {'lenient':>8} {'strict':>7} {'lost content on approved pages (mean / p95 / max)':>52}"
        )
        for t in (0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99):
            approved = [r for r in rows if r["est"] >= t]
            lenient = sum(r["truth"] < truth_bar for r in approved)
            strict = sum(r["est"] < t and r["truth"] >= truth_bar for r in rows)
            lost = sorted(1 - r["truth"] for r in approved) or [0.0]
            print(
                f"  {t:>9.0%} {len(approved) / n:>10.1%} {lenient:>8} {strict:>7}   "
                f"{statistics.mean(lost):>12.1%} / {quantile(lost, 0.95):.1%} / {lost[-1]:.1%}"
            )
    worst = sorted((r for r in rows if r["est"] >= 0.95), key=lambda r: r["truth"])[:8]
    print("\napproved at 95% but holding the least stable content:")
    for r in worst:
        print(f"  est {r['est']:.0%}  truth {r['truth']:.0%}  {r['url'][:90]}")


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
        asyncio.run(run(open(args.urls).read().split(), args.out, args.parallel))
    else:
        report(args.results)


if __name__ == "__main__":
    main()
