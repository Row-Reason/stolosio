"""Bounded capture load through the public API, with separate gateway/origin outcomes.

Example:
uv run python scripts/pacing_load.py --base-url http://localhost:8412 \
  --url https://en.wikipedia.org/wiki/Rate_limiting --duration 300 \
  --offered-rps 4 --workers 8 --max-captures 400 --output /tmp/pacing-load

This does not change policies, fabricate method-cache evidence, rotate egress or solve challenges.
The offered rate is a ceiling on calls to Stolosio, not individual outgoing browser requests.
"""

import argparse
import asyncio
import json
import math
import random
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx


async def run(args: argparse.Namespace) -> dict:
    hostnames = {urlsplit(url).hostname for url in args.url}
    if len(hostnames) != 1 or None in hostnames:
        raise ValueError("Use canonical URLs for exactly one hostname")
    hostname = hostnames.pop()
    started = time.monotonic()
    end = started + args.duration
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    records: list[dict] = []
    snapshots: list[dict] = []
    stopped = asyncio.Event()
    gate = asyncio.Lock()
    next_start = started
    pause_until = started
    admitted = 0
    attempts = 0

    args.output.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=65, trust_env=False) as client:
        settings_response = await client.get("/v1/admin/domain-pacing/settings")
        settings_response.raise_for_status()
        settings = settings_response.json()

        async def policy() -> dict | None:
            response = await client.get("/v1/admin/domain-pacing", params={"hostname": hostname})
            response.raise_for_status()
            rows = response.json()
            return rows[0] if rows else None

        async def monitor() -> None:
            last_generation = None
            while not stopped.is_set():
                value = await policy()
                snapshot = {"elapsed_s": round(time.monotonic() - started, 3), "policy": value}
                snapshots.append(snapshot)
                if value and value["generation"] != last_generation:
                    print(json.dumps({"event": "policy", **snapshot}), flush=True)
                    last_generation = value["generation"]
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=2)
                except TimeoutError:
                    pass

        async def worker(index: int) -> None:
            nonlocal next_start, pause_until, admitted, attempts
            while not stopped.is_set() and time.monotonic() < end:
                async with gate:
                    start_at = max(next_start, pause_until, time.monotonic())
                    next_start = start_at + 1 / args.offered_rps
                if start_at >= end:
                    break
                await asyncio.sleep(max(0, start_at - time.monotonic()))
                if stopped.is_set() or admitted >= args.max_captures:
                    break
                # A cooldown observed by another worker invalidates already scheduled starts.
                if time.monotonic() < pause_until:
                    continue
                number = attempts
                attempts += 1
                url = args.url[number % len(args.url)]
                began = time.monotonic()
                response = await client.post(
                    "/v1/capture",
                    json={
                        "url": url,
                        "resolve_bot_challenges": False,
                        "deadline_ms": 45000,
                        "reference": f"pacing-load-{run_id}-{index}-{number}",
                    },
                )
                response.raise_for_status() if response.status_code >= 500 else None
                result = response.json()
                failure = result.get("failure") or {}
                evidence = result.get("evidence") or {}
                steps = evidence.get("attempts") or []
                retry = failure.get("retry_after_seconds")
                row = {
                    "elapsed_s": round(began - started, 3),
                    "finished_s": round(time.monotonic() - started, 3),
                    "duration_s": round(time.monotonic() - began, 3),
                    "url": url,
                    "gateway_status": response.status_code,
                    "outcome": result.get("outcome"),
                    "failure_code": failure.get("code"),
                    "failure_category": failure.get("category"),
                    "reason": failure.get("message") if response.status_code == 429 else None,
                    "retry_after_seconds": retry,
                    "attempts": [
                        {
                            "tier": step["tier"],
                            "status_code": step.get("status_code"),
                            "duration_ms": step["duration_ms"],
                            "decision": step["decision"],
                            "reason": step.get("reason_code"),
                        }
                        for step in steps
                    ],
                }
                records.append(row)
                with (args.output / "captures.jsonl").open("a") as output:
                    output.write(json.dumps(row) + "\n")
                if response.status_code != 429:
                    admitted += 1
                if failure.get("code") == "rate_limited":
                    delay = float(retry) if retry is not None else 30
                    if not math.isfinite(delay) or delay < 0:
                        delay = 30
                    pause_until = max(pause_until, time.monotonic() + delay)
                    print(json.dumps({"event": "origin_throttle", **row}), flush=True)
                if failure.get("code") in {
                    "browser_unavailable",
                    "deadline_exceeded",
                    "unreachable",
                }:
                    recent = [r for r in records[-20:] if r["gateway_status"] != 429]
                    if len(recent) >= 5 and sum(r["outcome"] == "failed" for r in recent) >= 5:
                        print(
                            "Stopping: acquisition failures prevent meaningful learning", flush=True
                        )
                        stopped.set()
                if response.status_code == 429:
                    delay = float(response.headers.get("Retry-After", "1"))
                    if failure.get("message") == "domain_cooldown":
                        pause_until = max(pause_until, time.monotonic() + delay)
                    await asyncio.sleep(
                        min(delay + random.uniform(0.01, 0.1), max(0, end - time.monotonic()))
                    )
                if admitted >= args.max_captures:
                    stopped.set()

        async def progress() -> None:
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=20)
                except TimeoutError:
                    print(
                        json.dumps(
                            {
                                "event": "progress",
                                "elapsed_s": round(time.monotonic() - started),
                                "api_calls": len(records),
                                "completed_captures": admitted,
                                "outcomes": dict(
                                    Counter(r["failure_code"] or r["outcome"] for r in records)
                                ),
                            }
                        ),
                        flush=True,
                    )

        background = [asyncio.create_task(monitor()), asyncio.create_task(progress())]
        try:
            await asyncio.gather(*(worker(i) for i in range(args.workers)))
        finally:
            stopped.set()
            await asyncio.gather(*background)
            final_policy = await policy()
            (args.output / "policies.json").write_text(json.dumps(snapshots, indent=2) + "\n")
            latencies = [r["duration_s"] for r in records if r["outcome"] == "captured"]
            summary = {
                "run_id": run_id,
                "hostname": hostname,
                "settings": settings,
                "duration_s": round(time.monotonic() - started, 3),
                "offered_rps_ceiling": args.offered_rps,
                "workers": args.workers,
                "api_calls": len(records),
                "completed_captures": admitted,
                "gateway_statuses": dict(Counter(r["gateway_status"] for r in records)),
                "outcomes": dict(Counter(r["failure_code"] or r["outcome"] for r in records)),
                "origin_statuses": dict(
                    Counter(str(step["status_code"]) for r in records for step in r["attempts"])
                ),
                "successful_capture_median_s": statistics.median(latencies) if latencies else None,
                "final_policy": final_policy,
            }
            (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps({"event": "summary", **summary}), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--duration", type=float, default=300)
    parser.add_argument("--offered-rps", type=float, default=4)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-captures", type=int, default=400)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (
        0 < args.duration <= 600
        and 0 < args.offered_rps <= 10
        and 1 <= args.workers <= 8
        and 1 <= args.max_captures <= 1000
    ):
        parser.error("Require duration <=600s, offered rate <=10/s, workers <=8, captures <=1000")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
