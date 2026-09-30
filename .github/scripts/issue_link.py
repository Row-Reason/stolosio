"""Issue-link gate: every pull request must close an issue in this repository.

Runs from the base branch under ``pull_request_target`` with a read-only token. It reads
the pull request's current metadata from the GitHub API, never the event payload, so a
re-run after an edit always evaluates the latest body, labels and author. PR text is
never echoed into workflow output.

Usage: GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo PR_NUMBER=N python issue_link.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

DEPENDABOT_LOGIN = "dependabot[bot]"
EMERGENCY_LABEL = "emergency"
MIN_EMERGENCY_EXPLANATION = 20

_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_MARKER = r"(?:[-*+] +)?"
_CLOSES_SHORT = re.compile(rf"^ {{0,3}}{_LIST_MARKER}closes +#(\d+)[ \t]*\.?[ \t]*$", re.I)
_CLOSES_URL = re.compile(
    rf"^ {{0,3}}{_LIST_MARKER}closes +https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)"
    r"/?[ \t]*\.?[ \t]*$",
    re.I,
)
_CLOSES_PLACEHOLDER = re.compile(rf"^ {{0,3}}{_LIST_MARKER}closes +#n\b", re.I)
_EMERGENCY = re.compile(rf"^ {{0,3}}{_LIST_MARKER}emergency: *(.*)$", re.I)


class IssueKind(Enum):
    ISSUE = "issue"
    PULL_REQUEST = "pull request"
    MISSING = "missing"
    OTHER_REPOSITORY = "other repository"


IssueLookup = Callable[[int], IssueKind]


@dataclass
class Outcome:
    passed: bool
    result: str
    details: list[str] = field(default_factory=list)


def visible_lines(body: str) -> list[str]:
    """Return body lines outside HTML comments and fenced code blocks."""
    text = _HTML_COMMENT.sub("", body.replace("\r\n", "\n").replace("\r", "\n"))
    lines: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        match = _FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                continue
            lines.append(line)
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            if not line.strip().lstrip(fence[0]):
                fence = None
    return lines


@dataclass
class References:
    numbers: list[int] = field(default_factory=list)
    foreign: int = 0
    placeholders: int = 0


def closing_references(body: str, repository: str) -> References:
    """Find ``Closes #N`` lines (or same-repository issue URLs) in the rendered body."""
    refs = References()
    for line in visible_lines(body):
        if short := _CLOSES_SHORT.match(line):
            refs.numbers.append(int(short.group(1)))
        elif url := _CLOSES_URL.match(line):
            if url.group(1).lower() == repository.lower():
                refs.numbers.append(int(url.group(2)))
            else:
                refs.foreign += 1
        elif _CLOSES_PLACEHOLDER.match(line):
            refs.placeholders += 1
    refs.numbers = list(dict.fromkeys(refs.numbers))
    return refs


def emergency_explained(body: str) -> bool:
    for line in visible_lines(body):
        if match := _EMERGENCY.match(line):
            explanation = match.group(1).strip()
            if len(explanation) >= MIN_EMERGENCY_EXPLANATION and not explanation.startswith("<"):
                return True
    return False


def evaluate(pr: dict, repository: str, lookup: IssueLookup) -> Outcome:
    """Decide the check result from current pull request metadata."""
    author = pr.get("user") or {}
    if author.get("login") == DEPENDABOT_LOGIN and author.get("type") == "Bot":
        return Outcome(
            True,
            "Exempt: authored by dependabot[bot]",
            ["Dependency bumps by Dependabot are exempt and reported separately."],
        )

    body = pr.get("body") or ""
    refs = closing_references(body, repository)
    details: list[str] = []
    valid: list[int] = []
    for number in refs.numbers:
        kind = lookup(number)
        if kind is IssueKind.ISSUE:
            valid.append(number)
        else:
            details.append(
                f"`Closes #{number}` does not name an issue in this repository ({kind.value})."
            )
    if refs.foreign:
        details.append("Closing references to other repositories do not count.")
    if refs.placeholders:
        details.append("Replace the `#N` placeholder with the implementing issue number.")

    if valid and len(valid) == len(refs.numbers):
        closes = ", ".join(f"#{number}" for number in valid)
        return Outcome(True, f"Linked: closes {closes}", details)

    labels = {label.get("name", "").lower() for label in pr.get("labels") or []}
    if EMERGENCY_LABEL in labels:
        if emergency_explained(body):
            return Outcome(
                True,
                "Bypassed: emergency label",
                details
                + [
                    "This PR skipped the issue link under the maintainer-granted `emergency` "
                    "label. Create an issue now and add `Closes #N` to this PR.",
                    "The label waives only this check; it does not authorize deployment.",
                ],
            )
        return Outcome(
            False,
            "Failed: emergency label without explanation",
            details
            + [
                "An `emergency` PR must contain an `Emergency: <reason>` line explaining the "
                f"emergency (at least {MIN_EMERGENCY_EXPLANATION} characters).",
            ],
        )

    if not refs.numbers:
        details.append(
            "Add a line `Closes #N` naming the issue this PR implements. Mentions, "
            "comments and code blocks do not count."
        )
    return Outcome(False, "Failed: no valid closing issue reference", details)


class GitHub:
    def __init__(self, token: str, repository: str, api_url: str = "https://api.github.com"):
        self._token = token
        self._repository = repository
        self._api_url = api_url.rstrip("/")

    def _get(self, path: str) -> dict | None:
        request = urllib.request.Request(
            f"{self._api_url}/repos/{self._repository}/{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                return None
            raise

    def pull_request(self, number: int) -> dict:
        pr = self._get(f"pulls/{number}")
        if pr is None:
            raise RuntimeError(f"pull request #{number} not found")
        return pr

    def issue_kind(self, number: int) -> IssueKind:
        issue = self._get(f"issues/{number}")
        if issue is None:
            return IssueKind.MISSING
        if "pull_request" in issue:
            return IssueKind.PULL_REQUEST
        prefix = f"https://github.com/{self._repository}/issues/".lower()
        if not str(issue.get("html_url", "")).lower().startswith(prefix):
            return IssueKind.OTHER_REPOSITORY
        return IssueKind.ISSUE


def report(outcome: Outcome) -> None:
    lines = [f"### Issue link: {outcome.result}", ""] + [f"- {d}" for d in outcome.details]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    level = "notice" if outcome.passed else "error"
    print(f"::{level} title=Issue link::{outcome.result}")
    for detail in outcome.details:
        print(detail)


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    number = int(os.environ["PR_NUMBER"])
    github = GitHub(
        os.environ["GITHUB_TOKEN"],
        repository,
        os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    try:
        outcome = evaluate(github.pull_request(number), repository, github.issue_kind)
    except (urllib.error.URLError, RuntimeError, ValueError) as error:
        outcome = Outcome(False, "Failed: GitHub API error", [type(error).__name__])
        if isinstance(error, urllib.error.HTTPError):
            outcome.details = [f"HTTP {error.code} from the GitHub API"]
    report(outcome)
    return 0 if outcome.passed else 1


if __name__ == "__main__":
    sys.exit(main())
