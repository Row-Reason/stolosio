import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[2] / ".github" / "scripts" / "issue_link.py"
_spec = importlib.util.spec_from_file_location("issue_link", _PATH)
assert _spec and _spec.loader
issue_link = importlib.util.module_from_spec(_spec)
sys.modules["issue_link"] = issue_link
_spec.loader.exec_module(issue_link)

IssueKind = issue_link.IssueKind
REPO = "elei-io/stolosio"
TEMPLATE = (Path(__file__).parents[2] / ".github" / "pull_request_template.md").read_text()
EMERGENCY = "Emergency: capture endpoint returns 500 for every request in production"

KINDS = {
    53: IssueKind.ISSUE,
    7: IssueKind.ISSUE,  # closed issues remain valid for follow-up work
    38: IssueKind.PULL_REQUEST,
    99: IssueKind.OTHER_REPOSITORY,
}


def lookup(number: int) -> IssueKind:
    return KINDS.get(number, IssueKind.MISSING)


def pr(
    body: str | None,
    *,
    login: str = "ekkuleivonen",
    user_type: str = "User",
    labels: tuple[str, ...] = (),
) -> dict:
    return {
        "user": {"login": login, "type": user_type},
        "body": body,
        "labels": [{"name": name} for name in labels],
    }


def check(body: str | None, **kwargs) -> issue_link.Outcome:
    return issue_link.evaluate(pr(body, **kwargs), REPO, lookup)


@pytest.mark.parametrize(
    "body",
    [
        "Closes #53",
        "closes #53",
        "CLOSES #53.",
        "Summary\r\n\r\nCloses #53\r\n",
        "- Closes #53",
        "Closes https://github.com/elei-io/stolosio/issues/53",
        "Closes https://github.com/Elei-IO/Stolosio/issues/53/",
        "Closes #7",
        "Closes #53\nCloses #7",
        TEMPLATE.replace("Closes #N", "Closes #53"),
    ],
)
def test_valid_issue_reference_passes(body: str) -> None:
    outcome = check(body)
    assert outcome.passed, outcome
    assert outcome.result.startswith("Linked")


@pytest.mark.parametrize(
    "body",
    [
        None,
        "",
        "Implements the gate.",
        TEMPLATE,  # unmodified placeholder
        "Closes #",
        "Closes #99999",  # nonexistent
        "Closes #38",  # a pull request
        "Closes #99",  # transferred to another repository
        "Closes other-org/other#53",
        "Closes https://github.com/other-org/stolosio/issues/53",
        "Closes https://github.com/elei-io/stolosio/pull/53",
        "See #53 for context.",  # bare mention
        "This PR closes #53 as well.",  # mid-sentence, not a closing line
        "<!-- Closes #53 -->",
        "```\nCloses #53\n```",
        "~~~~markdown\nCloses #53\n~~~~",
        "`Closes #53`",
        "> Closes #53",
        "    Closes #53",  # indented code block
        "Closes #53 and #7",
        "Closes #53\nCloses #38",  # every closing reference must be valid
    ],
)
def test_missing_or_invalid_reference_fails(body: str | None) -> None:
    outcome = check(body)
    assert not outcome.passed, outcome


def test_unterminated_fence_hides_rest_of_body() -> None:
    assert not check("```\nCloses #53").passed
    assert check("```\nCloses #38\n```\nCloses #53").passed


def test_placeholder_gets_hint() -> None:
    outcome = check(TEMPLATE)
    assert any("placeholder" in detail for detail in outcome.details)


def test_body_corrected_after_failure_passes_on_reevaluation() -> None:
    assert not check("Closes #N").passed
    assert check("Closes #53").passed


def test_emergency_label_bypasses_with_visible_result() -> None:
    outcome = check(EMERGENCY, labels=("emergency",))
    assert outcome.passed
    assert outcome.result == "Bypassed: emergency label"
    assert any("Create an issue" in detail for detail in outcome.details)
    assert any("does not authorize deployment" in detail for detail in outcome.details)


@pytest.mark.parametrize(
    "body",
    [
        "",
        "Emergency:",
        "Emergency: urgent",
        "Emergency: <what broke and why it could not wait for an issue>",
        f"<!-- {EMERGENCY} -->",
        TEMPLATE,
    ],
)
def test_emergency_label_requires_explanation(body: str) -> None:
    outcome = check(body, labels=("emergency",))
    assert not outcome.passed
    assert "emergency" in outcome.result


def test_emergency_text_without_label_does_not_bypass() -> None:
    assert not check(EMERGENCY).passed
    assert not check(EMERGENCY, labels=("hotfix", "urgent")).passed


def test_emergency_label_removed_fails_again() -> None:
    assert check(EMERGENCY, labels=("emergency",)).passed
    assert not check(EMERGENCY).passed


def test_valid_link_with_emergency_label_is_linked_not_bypassed() -> None:
    outcome = check("Closes #53", labels=("emergency",))
    assert outcome.passed
    assert outcome.result.startswith("Linked")


def test_dependabot_author_is_exempt() -> None:
    outcome = check("Bumps sonner from 2.0.7 to 2.0.8.", login="dependabot[bot]", user_type="Bot")
    assert outcome.passed
    assert outcome.result == "Exempt: authored by dependabot[bot]"


@pytest.mark.parametrize(
    ("login", "user_type", "body", "labels"),
    [
        # Human author spoofing Dependabot through labels, body or commit text.
        (
            "ekkuleivonen",
            "User",
            "Bumps sonner.\n\nSigned-off-by: dependabot[bot]",
            ("dependencies", "javascript"),
        ),
        ("ekkuleivonen", "User", "Author: dependabot[bot]", ()),
        ("dependabot", "User", "Bumps sonner.", ()),
        ("dependabot[bot]", "User", "Bumps sonner.", ()),
        # Other bots are not exempt.
        ("github-actions[bot]", "Bot", "Automated update.", ()),
        ("renovate[bot]", "Bot", "Update dependency sonner.", ("dependencies",)),
    ],
)
def test_spoofed_dependabot_and_other_bots_are_not_exempt(
    login: str, user_type: str, body: str, labels: tuple[str, ...]
) -> None:
    outcome = check(body, login=login, user_type=user_type, labels=labels)
    assert not outcome.passed


class _FakeGitHub(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, object]] = {}

    def do_GET(self) -> None:  # noqa: N802
        status, payload = self.routes.get(self.path, (404, {"message": "Not Found"}))
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def fake_github() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _FakeGitHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _run(monkeypatch, api_url: str, tmp_path: Path, routes: dict) -> tuple[int, str]:
    _FakeGitHub.routes = routes
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("PR_NUMBER", "60")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_API_URL", api_url)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = issue_link.main()
    return code, summary.read_text()


def _issue(number: int, **extra) -> dict:
    return {"html_url": f"https://github.com/{REPO}/issues/{number}", **extra}


def test_main_reads_current_metadata_and_verifies_issue(monkeypatch, fake_github, tmp_path):
    routes = {
        f"/repos/{REPO}/pulls/60": (200, pr("Closes #53")),
        f"/repos/{REPO}/issues/53": (200, _issue(53, state="closed")),
    }
    code, summary = _run(monkeypatch, fake_github, tmp_path, routes)
    assert code == 0
    assert "Linked: closes #53" in summary


def test_main_rejects_pull_request_and_missing_issue(monkeypatch, fake_github, tmp_path):
    routes = {
        f"/repos/{REPO}/pulls/60": (200, pr("Closes #38")),
        f"/repos/{REPO}/issues/38": (200, _issue(38, pull_request={"url": "..."})),
    }
    assert _run(monkeypatch, fake_github, tmp_path, routes)[0] == 1
    routes = {f"/repos/{REPO}/pulls/60": (200, pr("Closes #404"))}
    assert _run(monkeypatch, fake_github, tmp_path, routes)[0] == 1


@pytest.mark.parametrize("status", [401, 403, 500, 502])
def test_main_treats_api_errors_as_failures(monkeypatch, fake_github, tmp_path, status):
    routes = {
        f"/repos/{REPO}/pulls/60": (200, pr("Closes #53")),
        f"/repos/{REPO}/issues/53": (status, {"message": "error"}),
    }
    code, summary = _run(monkeypatch, fake_github, tmp_path, routes)
    assert code == 1
    assert f"HTTP {status}" in summary


def test_main_fails_when_pull_request_cannot_be_read(monkeypatch, fake_github, tmp_path):
    code, summary = _run(monkeypatch, fake_github, tmp_path, {})
    assert code == 1
    assert "GitHub API error" in summary


def test_main_does_not_echo_pr_text(monkeypatch, fake_github, tmp_path, capsys):
    body = "::add-mask::x\n::error::spoofed\n" + EMERGENCY
    routes = {f"/repos/{REPO}/pulls/60": (200, pr(body, labels=("emergency",)))}
    code, summary = _run(monkeypatch, fake_github, tmp_path, routes)
    assert code == 0
    output = capsys.readouterr().out + summary
    assert "spoofed" not in output
    assert "production" not in output
