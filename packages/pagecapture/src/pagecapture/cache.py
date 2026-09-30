"""Remembering where plain HTTP is enough, so those pages can skip the browser.

Every render is compared with the plain response already fetched. The result is recorded at two levels:

- exact URL (host + path + query): pays off on recrawls;
- URL pattern (host + path with ids and slugs generalised, the last segment of paths two or more segments deep
  always generalised, query parameter names only): pays off on new pages that share a known layout, e.g.
  `en.wikipedia.org/wiki/*` or `news.example.com/{id}/{id}/{id}/*`.

A capture skips rendering only on evidence: the exact URL was HTTP-sufficient last time, or the pattern has at
least `pattern_min_comparisons` sufficient comparisons and hasn't been contradicted twice. Entries expire after
`cache_ttl_days` without being seen. The service still renders a canary share of cached captures, and whenever the
plain response looks different from usual, so the evidence keeps refreshing itself.
"""

import json
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qsl, urlparse

from .config import Settings

DAY = 86400.0


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")


def _generalise(segment: str) -> str:
    """A path segment as it would look across pages of the same layout."""
    if (
        re.fullmatch(r"\d+", segment)
        or re.search(r"\d{3,}", segment)
        or re.fullmatch(r"[0-9a-f]{8,}(-[0-9a-f]{4,})*", segment, re.I)
    ):
        return "{id}"
    if segment.count("-") >= 2 or segment.count("_") >= 2 or len(segment) > 24:
        return "*"
    return segment.lower()


def url_keys(url: str) -> tuple[str, str]:
    """(exact key, pattern key) for a URL."""
    u = urlparse(url)
    query = sorted(parse_qsl(u.query, keep_blank_values=True))
    path = u.path or "/"
    exact = _host(url) + path + ("?" + "&".join(f"{k}={v}" for k, v in query) if query else "")
    raw = [s for s in path.split("/") if s]
    segments = [_generalise(s) for s in raw]
    if len(raw) >= 2 and segments[-1] != "{id}":
        segments[-1] = "*"  # the last segment is almost always the page's own identifier (title, slug, id)
    names = sorted({k for k, _ in query})
    pattern = _host(url) + "/" + "/".join(segments) + ("?" + "&".join(names) if names else "")
    return "url:" + exact, "pattern:" + pattern


@dataclass
class MethodEntry:
    comparisons: int = 0  # renders compared with the plain response
    sufficient: int = 0  # ... where the plain response had the rendered content
    contradictions: int = 0  # ... where it didn't
    last_seen: float = 0.0
    typical_bytes: float = 0.0  # plain response size, smoothed
    last_sufficient: bool = False


class MethodCache(Protocol):
    """Storage for method entries; a host service backs it with its own database (stolosio: PostgreSQL)."""

    async def get(self, key: str) -> MethodEntry | None: ...
    async def put(self, key: str, entry: MethodEntry) -> None: ...


class MemoryMethodCache:
    def __init__(self):
        self._data: dict[str, MethodEntry] = {}

    async def get(self, key: str) -> MethodEntry | None:
        return self._data.get(key)

    async def put(self, key: str, entry: MethodEntry) -> None:
        self._data[key] = entry


class SqliteMethodCache:
    """A small persistent cache for single-process use (the CLI and benchmarks). Lookups are sub-millisecond, so
    they run inline."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS method (key TEXT PRIMARY KEY, entry TEXT NOT NULL)")
        self._lock = threading.Lock()

    async def get(self, key: str) -> MethodEntry | None:
        with self._lock:
            row = self._db.execute("SELECT entry FROM method WHERE key = ?", (key,)).fetchone()
        return MethodEntry(**json.loads(row[0])) if row else None

    async def put(self, key: str, entry: MethodEntry) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO method (key, entry) VALUES (?, ?)", (key, json.dumps(asdict(entry)))
            )
            self._db.commit()


class MethodPolicy:
    """Decides from the cache whether a capture may skip rendering, and records comparisons."""

    def __init__(self, cache: MethodCache, settings: Settings):
        self.cache, self.s = cache, settings

    async def _fresh(self, key: str, now: float) -> MethodEntry | None:
        entry = await self.cache.get(key)
        if entry and now - entry.last_seen > self.s.cache_ttl_days * DAY:
            return None  # expired: start over
        return entry

    async def http_sufficient(self, url: str, http_bytes: int) -> str | None:
        """A reason to trust the plain response without rendering, or None."""
        now = time.time()
        exact_key, pattern_key = url_keys(url)

        def usual(e: MethodEntry) -> bool:
            return e.typical_bytes <= 0 or 0.5 * e.typical_bytes <= http_bytes <= 2.0 * e.typical_bytes

        exact = await self._fresh(exact_key, now)
        if exact and exact.last_sufficient and usual(exact):
            return f"cache: this URL was HTTP-sufficient ({exact.sufficient}/{exact.comparisons})"
        pattern = await self._fresh(pattern_key, now)
        if (
            pattern
            and pattern.sufficient >= self.s.pattern_min_comparisons
            and pattern.contradictions < self.s.pattern_max_contradictions
            and usual(pattern)
        ):
            return (
                f"cache: pattern {pattern_key.removeprefix('pattern:')} HTTP-sufficient "
                f"({pattern.sufficient}/{pattern.comparisons})"
            )
        return None

    async def record(self, url: str, sufficient: bool, http_bytes: int) -> None:
        now = time.time()
        for key in url_keys(url):
            entry = await self._fresh(key, now) or MethodEntry()
            entry.comparisons += 1
            if sufficient:
                entry.sufficient += 1
            else:
                entry.contradictions += 1
                if key.startswith("url:"):
                    entry.sufficient = 0  # a URL contradicted once is invalid at once
            entry.last_sufficient = sufficient
            entry.typical_bytes = (
                http_bytes if entry.typical_bytes <= 0 else 0.8 * entry.typical_bytes + 0.2 * http_bytes
            )
            entry.last_seen = now
            await self.cache.put(key, entry)


def default_cache(settings: Settings) -> MethodCache:
    return SqliteMethodCache(Path(settings.method_cache_path)) if settings.method_cache_path else MemoryMethodCache()
