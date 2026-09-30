"""Command line.

  pagecapture capture <url> [--resolve-bot-challenges] [--html FILE] [--json [--body]]
  pagecapture classify <url> [--full] [--json]       classify the plain HTTP response only

Settings come from the environment (PAGECAPTURE_*): `uv run --env-file .env pagecapture …`.
"""

import argparse
import json

from .config import REPO_DIR, Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pagecapture", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("capture", help="capture a URL (docs/api.md): trustworthy document or failure, with evidence")
    c.add_argument("url")
    c.add_argument("--resolve-bot-challenges", action="store_true", help="allow the challenge-resolution tier")
    c.add_argument("--html", help="write the captured document to this file")
    c.add_argument("--json", action="store_true", help="print the endpoint response body")
    c.add_argument("--body", action="store_true", help="with --json: include body_base64")
    k = sub.add_parser("classify", help="classify the plain HTTP response only")
    k.add_argument("url")
    k.add_argument("--full", action="store_true", help="evaluate every column instead of stopping when certain")
    k.add_argument("--json", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if not settings.method_cache_path:  # the CLI remembers across runs (a library host brings its own storage)
        settings.method_cache_path = str(REPO_DIR / ".cache" / "method_cache.sqlite")

    if args.command == "classify":
        from .classify import Classifier

        verdict = Classifier(settings).classify_url(args.url, full=args.full)
        if args.json:
            print(json.dumps(verdict.to_dict()))
            return
        print(
            f"{verdict.url}\n  usable as is: {not verdict.rejected}\n  reason:       {verdict.reason or '-'}\n"
            f"  confidence:   {verdict.confidence:.2f}"
        )
        for col in verdict.true_reasons():
            f = verdict.flags[col]
            print(f"    {col:20} {f.confidence:.2f}  {f.source}: {f.detail}")
        for note in verdict.notes:
            print(f"  note: {note}")
        print(f"  latency: {verdict.latency_ms:.0f} ms (after fetch)")
        return

    from .service import capture

    result = capture(args.url, resolve_bot_challenges=args.resolve_bot_challenges, settings=settings)
    if args.html and result.document:
        open(args.html, "wb").write(result.document.body)
    if args.json:
        print(json.dumps(result.to_json(include_body=args.body), ensure_ascii=False))
        return
    d, f = result.document, result.failure
    print(
        f"{result.requested_url}\n  outcome:  {result.outcome}"
        + (
            f"   failure: {f.code} ({f.category}, {'transient' if f.transient else 'permanent'})"
            + (f", retry after {f.retry_after_seconds:.0f}s" if f.retry_after_seconds else "")
            if f
            else ""
        )
    )
    print(f"  final:    {result.final_url}   status {result.response.status_code if result.response else '-'}")
    if d:
        print(f"  document: {d.representation}, {d.media_type}, {d.content_bytes:,} bytes")
    for a in result.evidence.attempts:
        print(
            f"  attempt:  {a.path}/{a.tier} {a.status_code} {a.duration_ms / 1000:.1f}s "
            f"[{a.assessment.primary or 'usable'}] -> {a.decision}: {a.decision_reason}"
        )
        for note in a.notes:
            print(f"            note: {note}")
    c = result.evidence.cost
    print(f"  cost:     browser {c.browser_seconds:.1f}s, paid {c.paid}, {c.bytes:,} bytes")


if __name__ == "__main__":
    main()
