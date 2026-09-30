"""Benchmark the adaptive renderer against plain HTTP and a generous "person" reference capture.

    uv run python benchmarks/render.py run  data/render_benchmark_urls.txt results/render.jsonl
    uv run python benchmarks/render.py report results/render.jsonl [--labels data/render_benchmark_labels.json]

Per URL, three captures through the browser fleet (PAGECAPTURE_BROWSER_WS):
  http       JavaScript off: what a plain HTTP fetch gives, measured the same way as the others
  adaptive   pagecapture's adaptive renderer (the production path)
  reference  a generous capture: full load, network idle, scroll to the end with long pauses, extra waits

Content is measured as visible text lines. A line counts as the page's content when at least two of the three
captures saw it (rotating ads, live counters and randomised modules drop out; so does a line only one capture
invented). Runs are appended and resumable: finished (url, method) pairs are skipped.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict

from _harness import quantile

from pagecapture.classify.rules import CHALLENGE_TEXT
from pagecapture.config import Settings
from pagecapture.fetch import USER_AGENT
from pagecapture.render import Renderer, content_lines


async def http_capture(renderer: Renderer, url: str) -> dict:
    browser = await renderer._connect()
    t0 = time.perf_counter()
    try:
        ctx = await browser.new_context(java_script_enabled=False, user_agent=USER_AGENT, locale="en-US")
        page = await ctx.new_page()
        await page.goto(url, wait_until="load", timeout=30000)
        lines = content_lines(await page.evaluate("() => document.body ? document.body.innerText : ''"))
        return {"lines": sorted(lines), "seconds": round(time.perf_counter() - t0, 2), "ok": True}
    except Exception as e:
        return {"lines": [], "seconds": round(time.perf_counter() - t0, 2), "ok": False, "error": repr(e)[:200]}
    finally:
        await browser.close()


async def reference_capture(renderer: Renderer, url: str) -> dict:
    browser = await renderer._connect()
    t0 = time.perf_counter()
    seen: set[str] = set()
    try:
        ctx = await browser.new_context(viewport={"width": 1366, "height": 900}, user_agent=USER_AGENT, locale="en-US")
        page = await ctx.new_page()
        await page.goto(url, wait_until="load", timeout=45000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        text = "() => document.body ? document.body.innerText : ''"
        await page.wait_for_timeout(3000)
        seen |= content_lines(await page.evaluate(text))
        for _ in range(30):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(1500)
            seen |= content_lines(await page.evaluate(text))
            if await page.evaluate("window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 5"):
                await page.wait_for_timeout(3000)
                before = len(seen)
                seen |= content_lines(await page.evaluate(text))
                if len(seen) == before:
                    break
        await page.wait_for_timeout(3000)
        seen |= content_lines(await page.evaluate(text))
        return {"lines": sorted(seen), "seconds": round(time.perf_counter() - t0, 2), "ok": True}
    except Exception as e:
        return {
            "lines": sorted(seen),
            "seconds": round(time.perf_counter() - t0, 2),
            "ok": bool(seen),
            "error": repr(e)[:200],
        }
    finally:
        await browser.close()


async def run(urls: list[str], out: str, parallel: int) -> None:
    done = set()
    try:
        done = {(r["url"], r["method"]) for r in map(json.loads, open(out))}
    except FileNotFoundError:
        pass
    sem = asyncio.Semaphore(parallel)
    async with Renderer(Settings()) as renderer:
        with open(out, "a") as sink:

            async def one(url: str):
                async with sem:
                    for method in ("http", "adaptive", "reference"):
                        if (url, method) in done:
                            continue
                        if method == "adaptive":
                            r = await renderer.render(url)
                            rec = {
                                "lines": sorted(r.lines),
                                "seconds": r.seconds,
                                "ok": bool(r.lines),
                                "items": r.items,
                                "requests": r.requests,
                                "bytes": r.bytes,
                                "virtualized": r.virtualized,
                                "steps": r.steps,
                                "error": r.error,
                            }
                        else:
                            rec = await (http_capture if method == "http" else reference_capture)(renderer, url)
                        rec.update(url=url, method=method)
                        sink.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        sink.flush()
                        print(
                            f"  {url[:60]:60} {method:9} {rec['seconds']:6.1f}s lines={len(rec['lines'])}",
                            file=sys.stderr,
                            flush=True,
                        )

            await asyncio.gather(*(one(u) for u in urls), return_exceptions=True)


def report(path: str, labels_path: str | None) -> None:
    labels = json.load(open(labels_path)) if labels_path else {}
    by = defaultdict(dict)
    for r in map(json.loads, open(path)):
        by[r["url"]][r["method"]] = r
    rows = []
    for url, m in by.items():
        if not all(k in m and m[k]["ok"] for k in ("http", "adaptive", "reference")):
            continue
        a, ref, http = set(m["adaptive"]["lines"]), set(m["reference"]["lines"]), set(m["http"]["lines"])
        content = (a & ref) | (a & http) | (ref & http)  # seen by at least two of the three captures
        if len(content) < 5:
            continue
        blocked = any(c in line.lower() for line in a for c in CHALLENGE_TEXT) and not any(
            c in line.lower() for line in http for c in CHALLENGE_TEXT
        )
        rows.append(
            {
                "url": url,
                "label": labels.get(url, "?"),
                "http": len(content & http) / len(content),
                "adaptive": len(content & a) / len(content),
                "reference": len(content & ref) / len(content),
                "blocked": blocked,
                "s": m["adaptive"]["seconds"],
                "ref_s": m["reference"]["seconds"],
                "http_s": m["http"]["seconds"],
            }
        )
    n = len(rows)
    print(f"{n} pages with all three captures ({len(by)} attempted)\n")
    h = [r["http"] for r in rows]
    print(
        f"plain HTTP already has ≥95% of the page's content: {sum(x >= 0.95 for x in h)} ({sum(x >= 0.95 for x in h) / n:.0%})"
    )
    print(
        f"HTTP has 80–95%:                                   {sum(0.8 <= x < 0.95 for x in h)} ({sum(0.8 <= x < 0.95 for x in h) / n:.0%})"
    )
    print(
        f"HTTP has under 80% (rendering matters):            {sum(x < 0.8 for x in h)} ({sum(x < 0.8 for x in h) / n:.0%})"
    )
    print(
        f"HTTP has under 50% (rendering essential):          {sum(x < 0.5 for x in h)} ({sum(x < 0.5 for x in h) / n:.0%})"
    )
    for name, key, t in (
        ("http", "http", "http_s"),
        ("adaptive", "adaptive", "s"),
        ("reference", "reference", "ref_s"),
    ):
        cov, secs = [r[key] for r in rows], sorted(r[t] for r in rows)
        print(
            f"\n{name:10} content {statistics.mean(cov):6.1%}   pages ≥95%: {sum(c >= 0.95 for c in cov)}/{n}   "
            f"time median {statistics.median(secs):.1f}s  p90 {quantile(secs, 0.9):.1f}s  mean {statistics.mean(secs):.1f}s"
        )
    print(f"\nbrowser got a challenge the plain fetch didn't: {sum(r['blocked'] for r in rows)} pages")
    if labels:
        for lab in sorted({r["label"] for r in rows}):
            sub = [r for r in rows if r["label"] == lab]
            print(
                f"  [{lab}] {len(sub)} pages: http {statistics.mean(r['http'] for r in sub):.0%}, "
                f"adaptive {statistics.mean(r['adaptive'] for r in sub):.0%}"
            )
    print("\nadaptive's lowest coverage:")
    for r in sorted(rows, key=lambda r: r["adaptive"])[:8]:
        print(f"  {r['adaptive']:5.0%} (http {r['http']:4.0%})  {r['url'][:90]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("urls")
    r.add_argument("out")
    r.add_argument("--parallel", type=int, default=3)
    p = sub.add_parser("report")
    p.add_argument("results")
    p.add_argument("--labels")
    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(run(open(args.urls).read().split(), args.out, args.parallel))
    else:
        report(args.results, args.labels)


if __name__ == "__main__":
    main()
