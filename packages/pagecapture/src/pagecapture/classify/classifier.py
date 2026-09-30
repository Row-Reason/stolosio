"""Classify a fetched response with rules: usable as it is, or rejected and why.

Rules run in priority order. At the first rejection they are certain about, classification stops (unless
full=True): every earlier column is already false, so that is the primary reason.

Whether a browser would add content is not judged from raw HTML any more: every usable page is rendered and
compared (service.py), unless the method cache has evidence that plain HTTP is enough. The only render-need signal
kept is near-certain rule evidence of an app shell (an empty mount point, a JavaScript notice), which sends the
page to the browser as missing content rather than as a page to verify.
"""

import asyncio
import time

from ..config import Settings
from ..document import Document
from ..fetch import Fetched
from ..labels import NO_CONTENT, REASONS, RENDER_NEED, Flag, Verdict
from . import rules


class Classifier:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def classify_url(self, url: str, full: bool = False) -> Verdict:
        """Fetch with the production fetcher, then classify (the CLI's `classify`)."""
        from ..adapters import FetchError, HttpxFetcher

        async def fetch():
            fetcher = HttpxFetcher(self.settings)
            try:
                return await fetcher.fetch(url, self.settings.http_timeout_s)
            finally:
                await fetcher.close()

        try:
            http = asyncio.run(fetch())
            fetched = Fetched(url, http.as_requests(), None)
        except FetchError as e:
            fetched = Fetched(url, None, str(e))
        return self.classify(fetched, full=full)

    def classify(self, fetched: Fetched, full: bool = False) -> Verdict:
        """full=True evaluates every column (for benchmarks); otherwise stop as soon as the outcome is certain."""
        start = time.perf_counter()
        verdict = self._classify(fetched, full)
        verdict.latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return verdict

    def _classify(self, fetched: Fetched, full: bool) -> Verdict:
        url, resp = fetched.url, fetched.response
        if resp is None:
            flags = {"unreachable": Flag(True, 1.0, "rule", fetched.error or "no HTTP response")}
            if full:
                flags.update({r: Flag(False, 1.0, "n/a") for r in REASONS[1:]})
            return Verdict.from_flags(url, flags, notes=[] if full else ["early exit: no HTTP response"])

        doc = Document(url, resp)
        rule_flags, stopped = rules.evaluate(doc, None if full else self.settings.early_exit_confidence)
        flags = {"unreachable": Flag(False, 1.0, "rule"), **rule_flags}
        if stopped:
            verdict = Verdict.from_flags(
                url, flags, notes=[f"early exit: rules are certain ({rules_primary(rule_flags)})"]
            )
        else:
            if not doc.is_markup or any(flags[c].value for c in NO_CONTENT):
                for c in RENDER_NEED:  # the page's content is the block itself, or there is no page
                    flags[c] = Flag(False, 1.0, "n/a", "no page content of its own to render")
            else:
                for c in RENDER_NEED:
                    flags[c] = Flag(False, 0.5, "n/a", "not assessed: the page is rendered and compared")
                evidence = rules.render_evidence(doc)
                if evidence:
                    flags["app_shell"] = Flag(True, 0.9, "rule", evidence)
            verdict = Verdict.from_flags(url, flags)
        verdict._document = doc  # the parsed page, for callers that need its text (not part of the verdict's data)
        return verdict


def rules_primary(flags: dict[str, Flag]) -> str:
    return next((f"{c}: {f.detail}" for c, f in flags.items() if f.value), "")
