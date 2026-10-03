# Local resolver baseline — 2026-10-03

Ran all **111 URLs** from the one-per-domain challenge dataset against the local
Docker Compose capture API (`http://localhost:8411`), using code at `0c3aa52`.
Two captures ran concurrently. Every request set `resolve_bot_challenges: false`
and `deadline_ms: 120000`; no paid tier was used. The local resolver retained its
native browser identity, 10-second challenge wait and 20-second attempt budget.
No production or homelab service was queried or modified.

## Results

| Result | URLs |
| --- | ---: |
| Usable local-resolution captures, after reviewing accepted outputs | 8 |
| Local acceptance that was actually an access-denied page | 1 |
| Captured normally without invoking local resolution | 3 |
| Usable HTTP content preserved after local resolution failed, unverified | 6 |
| Failed captures | 93 |
| Total | 111 |

The local resolver ran on **107 URLs**. It returned nine accepted captures;
reviewing their saved HTML identified eight usable responses. Thus the audited
local acquisition rate is **8/107 (7.5%)** of local attempts, or **8/111 (7.2%)** of
the full dataset. This is a single observed run, not a general solve-rate estimate.
One of the eight is a redirected landing page; seven retained the intended content
page rather than replacing an old article with a landing page.

There were **18 API-reported captures** in total. Only nine had an accepted local
attempt: an overall `captured` outcome after attempting local resolution is not
sufficient evidence of solver success. Six captures instead retained usable plain
HTTP after browser resolution failed, and three succeeded without local resolution.

## Usable local responses

| Domain | Local attempt seconds | Visible text characters | Note |
| --- | ---: | ---: | --- |
| www.euroleague.net | 10.51 | 12,383 | Old article redirects to the EuroLeague landing page; original article was not recovered. |
| www.superdeporte.es | 9.28 | 6,966 |  |
| math.stackexchange.com | 6.10 | 28,887 |  |
| observablehq.com | 5.74 | 20,540 |  |
| snaccooperative.org | 8.69 | 4,273 |  |
| ucatholic.com | 6.49 | 13,905 |  |
| www.dataversity.net | 5.80 | 9,202 |  |
| www.texasobserver.org | 5.11 | 4,977 |  |

Seven successes came from historically labelled challenges (7/77), and one from
historically labelled block pages (1/34). Those labels describe the previous dataset
observations; they do not identify today's protection vendor.

## Failures and false acceptance

| API failure code | URLs |
| --- | ---: |
| `bot_challenge` | 55 |
| `bot_blocked` | 30 |
| `access_denied` | 4 |
| `incomplete_content` | 2 |
| `browser_unavailable` | 1 |
| `not_found` | 1 |

Waarnemingen's Anubis/BotStopper response was accepted with HTTP 200, title
“Something went wrong!”, and 252 visible text characters. Its text explicitly said
“Access Denied”. It is excluded from the usable local count. This exposes a content
classification gap; the run did not change classifier or solver behavior to improve
its score.

EuroLeague's historical article URL redirects to its current landing page. The
resolver acquired that page successfully, but did not recover the original article.
The saved audit explicitly distinguishes this from same-target content acquisition.

Local attempt time: median **10.67 s**, p90
**13.07 s**, maximum **20.01 s**.
The local controller initially was not running, so the first two wall-clock durations
include capacity waiting. It was started before successful admission; per-attempt
solver timings above exclude that admission wait. All URLs ultimately received capture
results; there were no harness errors or unresolved capacity refusals.

## Evidence and scope

- [Per-URL compact baseline](../data/local_solver_baseline_2026-10-03.jsonl) includes
  API outcome, local decision/assessment, timing, title, content length and audit notes.
  It excludes response headers, cookies, document bodies and arbitrary failure text.
- Full local response evidence, CSV, run log and saved accepted HTML are under
  `results/local_solver_2026-10-03/` in the working checkout; they are not committed.
- [Dataset selection and provenance](challenge-dataset.md) describes the historical
  September 30 observations. Challenge behavior varies with time and egress identity.
- Reviewed all nine locally accepted HTML outputs for content versus challenge/error
  pages. This is a practical content check, not independent completeness ground truth
  for every page or a repeated reliability measurement.
- Paid fallback remained disabled; this run does not compare local versus paid performance.

Dataset SHA-256 (`local_solver_urls.txt`):
`4a86067ec53db3f733d8b16b37ba0829d582f5f2aa4633e05ae46cb3a89577cd`.
