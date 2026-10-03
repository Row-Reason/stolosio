# Contributing

Stolosio is experimental. Small bug fixes, reproducible reports, and documentation
improvements are welcome. Every change, however small, starts from a GitHub issue; see
[Issue-first changes](#issue-first-changes).

Follow the [README](README.md) for setup and [AGENTS.md](AGENTS.md) for implementation
conventions. Read the relevant architecture document before changing a public contract.

Before submitting a change:

```bash
uv sync --locked --dev
uv run ruff check .
uv run pytest -m "not e2e"
```

PostgreSQL and NATS must be running for integration tests; otherwise some tests skip.
For browser changes, also run `STOLOSIO_E2E=1 uv run pytest -m e2e` with the full
Compose stack and fleet controller running. Browserless cloud checks require a token
and may incur charges; the local provider tests do not require a paid account.

For frontend changes, run from `admin/`:

```bash
npm ci
npm run lint
npm run typecheck
npm run build
```

Describe the problem, the resulting behavior, and the checks you ran in your pull
request, and keep the template's `Closes #N` line. Add a focused regression test for behavior changes and update affected docs.
Never include credentials, private page content, or customer data in issues or tests.

## Issue-first changes

Every pull request must close an issue in this repository with a line of its own:

```text
Closes #123
```

`Closes https://github.com/elei-io/stolosio/issues/123` is equivalent, and the match is
case-insensitive. Closed issues are valid for follow-up work. The `Issue link` check
(`.github/workflows/issue-link.yml`) runs on every pull request, with no path filter, and
re-runs when the PR is opened, reopened, pushed to, edited, or labeled/unlabeled. It
reads the PR's current author, body and labels from the GitHub API, and fails when:

- no `Closes #N` line exists, or it still contains the template's `#N` placeholder;
- any referenced number is a pull request, does not exist, or lives in another
  repository;
- the reference is only a mention, sits mid-sentence, or appears inside an HTML comment
  or code block.

Two results pass without a link, and both say so in the check summary:

- **Dependabot.** PRs whose GitHub author is `dependabot[bot]` are exempt. Branch names,
  labels, titles, bodies and commit text do not count, and no other bot is exempt.
- **Emergency.** A maintainer may apply the `emergency` label when a fix cannot wait for
  an issue. The PR must then contain an `Emergency: <reason>` line explaining the
  emergency, and the author must create the issue afterwards and add `Closes #N`. Only
  maintainers should grant this label. It waives only the `Issue link` check; it does
  not authorize deployment or bypass any other check or review. Removing the label
  makes the check fail again until a link is added.

The workflow runs from the base branch under `pull_request_target` with a read-only
token, so a pull request cannot change the gate it is judged by, and PR-head code is
never checked out. Changes to the validator (`.github/scripts/issue_link.py`, tested in
`tests/github/`) therefore take effect only after they merge.

### Maintainer setup

A failing workflow alone does not block merges. A repository admin must:

1. Create the label once:
   `gh label create emergency -R elei-io/stolosio --color B60205 --description "Maintainer-granted bypass of the Issue link check only"`.
2. Require the check: **Settings → Rules → Rulesets → New branch ruleset**, target the
   default branch, enable **Require status checks to pass**, and add `Issue link`
   (source: GitHub Actions). Classic branch protection works too: **Settings →
   Branches → Add rule** for `main`, **Require status checks to pass before merging**,
   and select `Issue link`. The check must have run at least once after this workflow
   merges before GitHub offers it in the list.
