"""The label columns (see docs/labels.md) and the verdict every classification returns."""

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Reason columns in priority order: a verdict's primary reason is the first true one.
REASONS = (
    "unreachable",
    "payload_mismatch",
    "rate_limited",
    "bot_challenge",
    "geo_blocked",
    "unsupported_browser",
    "interstitial",
    "auth",
    "paywall",
    "parked",
    "gone",
    "not_found",
    "client_error",
    "server_error",
    "app_shell",
    "partial",
)
# Columns that ask "would a browser show content the raw HTML lacks?" (the service renders and compares instead;
# only rule evidence of an app shell is kept).
RENDER_NEED = ("app_shell", "partial")
# Columns decided by rules.
RULE_COLUMNS = tuple(r for r in REASONS if r not in RENDER_NEED)
# When one of these is true the page's own content is the block itself, so render need doesn't apply.
NO_CONTENT = ("unreachable", "payload_mismatch", "bot_challenge", "interstitial", "parked")


@dataclass
class Flag:
    """One column's decision: its value, the confidence in that value (0.5-1), and what decided it."""

    value: bool
    confidence: float
    source: str  # "rule" or "n/a"
    detail: str = ""


@dataclass
class Verdict:
    url: str
    rejected: bool
    reason: str | None  # primary reason, None when the response is usable as it is
    confidence: float
    flags: dict[str, Flag]
    latency_ms: float = 0.0
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_flags(cls, url: str, flags: dict[str, Flag], **kw) -> "Verdict":
        reason = primary(flags)
        # an acceptance is only as sure as the least sure "no"
        confidence = flags[reason].confidence if reason else min(f.confidence for f in flags.values())
        return cls(
            url=url, rejected=reason is not None, reason=reason, confidence=round(confidence, 4), flags=flags, **kw
        )

    def __getstate__(self) -> dict:
        # the parsed page callers may attach (`_document`) is a side channel: never pickled with the verdict
        return {k: v for k, v in self.__dict__.items() if k != "_document"}

    def true_reasons(self) -> list[str]:
        return [r for r in REASONS if r in self.flags and self.flags[r].value]

    def to_dict(self) -> dict:
        return asdict(self)


def primary(flags: dict[str, Flag]) -> str | None:
    """The first true column. Early-exit verdicts carry only the columns evaluated before the exit."""
    return next((r for r in REASONS if r in flags and flags[r].value), None)


def load_labels(path: Path) -> dict[str, set[str]]:
    """The audited labels: url -> set of true reason columns."""
    return {r["url"]: {c for c in REASONS if r[f"_{c}"] == "true"} for r in csv.DictReader(open(path))}
