# Local resolver experiments — 2026-10-03

Ran all **141 URLs** against the local Compose API using implementation commit
`05db188`, renderer `adaptive-6`, two concurrent requests, `deadline_ms: 120000`,
and **paid fallback disabled**. The run completed from 03:34:31 to 03:47:39 UTC.
Every URL received a result; no harness errors or paid attempts occurred.

## Results

| Cohort | URLs | Local attempts | Audited usable local responses | Rate per local attempt |
| --- | ---: | ---: | ---: | ---: |
| Original baseline, before changes | 111 | 107 | 8 | 7.5% |
| Original cohort, after changes | 111 | 108 | 8 | 7.4% |
| Added Periplus cohort, after changes | 30 | 29 | 16 | 55.2% |
| Expanded cohort, after changes | 141 | 137 | 24 | 17.5% |

**The original cohort gained no new usable local successes and lost none.** Its
rate changed slightly because PayPal now invoked a failed local attempt, whereas
the earlier run ended without one. The expanded rate does not demonstrate an
improvement over 7.5%: it includes a different set of domains. The additions have
no before-change control run. Both experiments were enabled together, so this
run cannot isolate their effects, and challenge behavior can change between runs.

As before, one original usable response is EuroLeague's redirected homepage,
not its historical article. Thus 23 of the 24 usable local responses retain the
intended content target; the strict target-content rate is 23/137 (16.8%).

| Expanded result category | URLs |
| --- | ---: |
| Audited usable local responses | 24 |
| Locally accepted but incomplete navigation-only page | 1 |
| API capture without a local attempt | 4 |
| Plain HTTP retained after local failure, unverified | 6 |
| Failed captures | 106 |

The API reported 35 captures and 25 local acceptances. Vestar's accepted output
contained navigation and year-in-review links, with an empty main element and no
substantive body content. It is excluded from the usable count. Waarnemingen's
HTTP-200 BotStopper denial is now correctly rejected as `bot_blocked`; the local
attempt recorded `challenge denied` and ended in 1.67 seconds, compared with
14.43 seconds and a false acceptance before the change.

Final failures: 64 `bot_challenge`, 35 `bot_blocked`, four `access_denied`, and
one each `browser_unavailable`, `incomplete_content` and `not_found`.
Local attempt duration: median **10.71 s**, p90 **13.19 s**, maximum **35.02 s**;
aggregate local time **1,387.17 s** across 137 attempts. The earlier 111-URL run's
median was 10.67 s and p90 13.07 s; aggregate times span different cohort sizes.

## Added cohort's usable local captures

36Kr, Advent International, Altinity, Cerberus, Golden Gate Capital,
Hellman & Friedman, H.I.G. Capital, Leonard Green, New Mountain Capital,
PAI Partners, Partners Group, Quadria Capital, Silver Lake, StarTree,
Veritas Capital and Vista Equity Partners.

## Implementation and validation

- The local tier permits images, fonts and media and uses CDP transfer accounting
  and the existing 20 MB transfer cap. URL exclusions and network policy remain
  enforced. Service workers remain blocked because the current page-scoped
  exclusion guard does not cover their requests reliably.
- The initial challenge wait remains 10 seconds. Changing Anubis progress signals
  can extend it up to 25 seconds, with a 35-second total local attempt budget,
  always bounded by the caller's remaining deadline. Explicit Anubis/BotStopper
  denials end the wait immediately and are rejected by content classification.
- Unit regressions cover progress, stalls, hard caps, immediate denials and the
  HTTP-200 BotStopper error. E2E fixtures verify image-dependent clearance and a
  challenge that progresses for 12 seconds before returning the complete article.
- **299 unit tests**, **eight capture E2E tests**, Ruff and diff whitespace checks
  passed. Initial E2E attempts raced local browser-container replacement during
  fleet startup; the complete suite passed after the fleet was stable.
- Reviewed all 25 locally accepted saved HTML outputs for content versus error,
  challenge or incomplete pages. This is a practical audit, not independent page
  completeness ground truth or a repeated reliability measurement.

## Evidence

[Compact per-URL results](../data/local_solver_v2_baseline_2026-10-03.jsonl)
identify each cohort, local decision, classification, title, timing and audit note.
Raw captures, run log and accepted HTML are local artifacts under
`results/local_solver_v2_2026-10-03/`; response headers were omitted, and page bodies
are not committed. The original [baseline](local-solver-baseline.md) is preserved.

Expanded dataset SHA-256 (`local_solver_expanded_urls.txt`):
`aee766906f5f76f917667fcc6680e17fee2dcf4078dedd156a2de6278815e47a`.
