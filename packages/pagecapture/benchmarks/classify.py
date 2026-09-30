"""Benchmark the rules against the audited labels (data/labels.csv).

    uv run python benchmarks/classify.py [--out results/classify.csv]

Each row is classified twice: in fast mode (the production path, with early exits; its latency is reported) and in
full mode (every column, for per-column metrics). The two must agree on the outcome and primary reason.

Render need (app_shell, partial) is no longer judged from raw HTML: the service renders and compares. Only the
rules' near-certain app-shell evidence is scored here; "accepted" means "not blocked or broken" (a page the service
goes on to render), so a label of app_shell or partial counts as accepted unless that evidence fires.
"""

import csv
import statistics
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from _harness import quantile

from pagecapture.classify import Classifier
from pagecapture.config import Settings
from pagecapture.fetch import from_record, load_snapshot
from pagecapture.labels import REASONS, RENDER_NEED, RULE_COLUMNS, Verdict, load_labels

_classifier = Classifier(Settings())


def _classify(rec: dict) -> tuple[Verdict, Verdict]:
    fetched = from_record(rec)
    fast = _classifier.classify(fetched)
    early = bool(fast.notes) and fast.notes[0].startswith("early exit")
    return fast, _classifier.classify(fetched, full=True) if early else fast


@dataclass
class RowResult:
    url: str
    labels: set[str]  # blocking reasons only (render need is decided by rendering)
    app_shell: bool
    fast: Verdict
    full: Verdict


def benchmark(settings: Settings, workers: int | None = None) -> list[RowResult]:
    labels = load_labels(settings.labels_csv)
    snapshot = load_snapshot(settings.snapshot)
    urls = [u for u in labels if u in snapshot]
    with ProcessPoolExecutor(workers) as pool:
        verdicts = list(pool.map(_classify, (snapshot[u] for u in urls), chunksize=8))
    return [
        RowResult(u, labels[u] - set(RENDER_NEED), "app_shell" in labels[u], fast, full)
        for u, (fast, full) in zip(urls, verdicts, strict=True)
    ]


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:5.1f}%" if d else "    -"


def blocking(v: Verdict) -> str | None:
    """The verdict's primary reason if it blocks the page (app_shell sends it to the browser instead)."""
    return v.reason if v.reason not in RENDER_NEED else None


def report(results: list[RowResult]) -> None:
    n = len(results)
    wrong_acc = sum(bool(r.labels) and not blocking(r.fast) for r in results)
    wrong_rej = sum(not r.labels and bool(blocking(r.fast)) for r in results)
    primary_ok = sum(next((c for c in REASONS if c in r.labels), None) == blocking(r.fast) for r in results)
    agree = sum(r.fast.reason == r.full.reason for r in results)
    early = sum(bool(r.fast.notes) and r.fast.notes[0].startswith("early exit") for r in results)
    lat = [r.fast.latency_ms for r in results]
    print(f"\n{n} rows")
    print(
        f"  blocked-or-not correct: {pct(n - wrong_acc - wrong_rej, n)}   missed blocks: {wrong_acc}   false blocks: {wrong_rej}"
    )
    print(f"  primary reason correct: {pct(primary_ok, n)}")
    print(f"  early exits: {early} ({pct(early, n).strip()}); fast and full mode agree on the reason: {agree}/{n}")
    print(
        f"  latency (fast mode, response in hand): p50 {statistics.median(lat):.0f} ms, p95 {quantile(lat, 0.95):.0f} ms"
    )

    shells = [r for r in results if not r.labels]
    tp = sum(
        r.app_shell and r.full.flags.get("app_shell") is not None and r.full.flags["app_shell"].value for r in shells
    )
    fired = sum(r.full.flags.get("app_shell") is not None and r.full.flags["app_shell"].value for r in shells)
    print(
        f"  app-shell evidence: fired on {fired} pages, {pct(tp, fired).strip()} of them labelled app_shell; "
        f"catches {tp}/{sum(r.app_shell for r in shells)} labelled app shells (the rest are rendered by default anyway)"
    )

    print("\nper column (full mode)")
    print(f"{'column':22} {'true':>5} {'prec':>6} {'recall':>6} {'F1':>5}")
    for c in RULE_COLUMNS:
        rows = [(c in r.labels, r.full.flags[c].value) for r in results if c in r.full.flags]
        tp = sum(t and p for t, p in rows)
        fp = sum(p and not t for t, p in rows)
        fn = sum(t and not p for t, p in rows)
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        print(f"_{c:21} {tp + fn:>5} {pct(tp, tp + fp):>6} {pct(tp, tp + fn):>6} {f1:>5.2f}")

    mistakes = Counter(
        (next((c for c in REASONS if c in r.labels), "accept"), blocking(r.fast) or "accept")
        for r in results
        if next((c for c in REASONS if c in r.labels), None) != blocking(r.fast)
    )
    print("\ntop primary-reason mistakes (label -> predicted):")
    for (label, pred), k in mistakes.most_common(10):
        print(f"  {k:>4}  {label} -> {pred}")


def write_csv(results: list[RowResult], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "labels", "reason", "confidence", "true_columns", "latency_ms", "notes"])
        for r in results:
            v = r.fast
            w.writerow(
                [
                    r.url,
                    " ".join(sorted(r.labels)),
                    v.reason or "",
                    v.confidence,
                    " ".join(r.full.true_reasons()),
                    v.latency_ms,
                    "; ".join(v.notes),
                ]
            )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="write per-row results to this CSV")
    args = parser.parse_args()
    results = benchmark(Settings())
    report(results)
    if args.out:
        write_csv(results, args.out)
        print(f"\nper-row results written to {args.out}")


if __name__ == "__main__":
    main()
