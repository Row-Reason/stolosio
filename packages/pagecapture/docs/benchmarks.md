# Benchmarks

All numbers from 2026-09-29, fetched from a Japanese IP, unless marked as the deployed service. Reproduce with the
commands below.

## Classification (`benchmarks/classify.py`)

1,836 audited raw responses (`data/`), scored against the rules (the only classifier since render need is
measured by rendering). "Blocked or not" = the page ends the capture (404, challenge, login wall, …) vs goes on
to be rendered.

```bash
uv run python benchmarks/classify.py [--out results/classify.csv]
```

| | Blocked-or-not correct | Missed blocks | False blocks | Primary reason correct | Latency p50 / p95 |
|---|---|---|---|---|---|
| rules before the 2026-09-30 review | 98.4% | 22 | 7 | 97.8% | 11 ms / 75 ms |
| **after** (tuned on these rows, see below) | **99.4%** | 9 | 2 | 98.9% | 11 ms / 85 ms |

The review of the 29 errors added general rules, not site lists: challenge, unsupported-device, request-failed,
service-ended (several languages), redirect-stub and age-gate wording; "Index of /" and web-server default pages as
parked; a redirect to a page titled "sign in", or to a 403 page; OAuth-only sign-in pages; a deep link redirected
to another site's front page as a soft 404 (unless the thing moved to its own domain, mozilla.org/firefox →
firefox.com). It removed false signals: `sec-container` (a common CSS class, not an Akamai challenge), redirect
stubs that are app shells, browser-update banners on real pages, login boxes on real pages, and paywall markup on
listings that also declare free items. Because these rows were used to find the fixes, 99.4% overstates; the
checks that weren't tuned on are the end-to-end sample and 200 unseen sites (below).

Still missed (9): blocks that only exist after JavaScript (reddit, x.com settings, cyon.ch: rendered anyway, and the
rules run again on the rendered page), a Finnish bank's login page, a country picker, and label judgement calls.

- Early exits on 24.7% of rows; fast and full mode agree on the primary reason for every row.
- F1 by column: unreachable 1.00, payload 1.00, client error 1.00, bot challenge 0.97, rate limited 0.97,
  not found 0.97, server error 0.97, paywall 0.96, auth 0.90, parked 0.86, gone 0.80, unsupported browser 0.77,
  interstitial 0.76, geo 0.67 (4 examples).
- App-shell evidence fires on 69 pages, 97% of them labelled app shells (they go to the browser as missing
  content); the other half of app shells are caught by rendering every page anyway.
- History: a learned render-need model plus an LLM second opinion (Jev) reached 82–85% accept/reject on the
  harder question "does the raw HTML lack content?" (`partial` precision ~40%). Rendering by default made that
  question moot, and they were removed.

## Rendering (`benchmarks/render.py`)

142 labelled pages (one per site; accepted, partial and app-shell pages), each captured with JavaScript off (≈
plain HTTP), with render policies, and with a generous reference. Coverage = share of content lines seen by
at least two captures.

```bash
uv run python benchmarks/render.py run data/render_benchmark_urls.txt results/render.jsonl
uv run python benchmarks/render.py report results/render.jsonl --labels data/render_benchmark_labels.json
```

| Policy | Content | Listing items | Median time | MB/page |
|---|---|---|---|---|
| JavaScript off (≈ HTTP) | 63% | 56% | 1.3 s | 0.07 |
| fixed: parse + 2 s, scroll to the end | 96.6% | 92% | 12.6 s | 2.7 |
| adaptive v2 (stop when scrolling stops paying) | 94.3% | 86% | 3.9 s | 1.8 |
| adaptive v3 | 96.4% | 97.6% | 7.3 s | 2.9 |
| reference ("a person") | 96.8% | 94% | 32.1 s | 8.3 |

Re-run 2026-09-30 with the current renderer (`adaptive-4`, after the busy-page, chunked-read and CDP-event fixes)
on 137 pages, content = lines seen by at least two of the three captures (plain HTTP, adaptive, reference):

| Capture | Content | Pages ≥95% | Median time | p90 time |
|---|---|---|---|---|
| JavaScript off (≈ HTTP) | 63.3% | 43/137 | 1.6 s | 4.6 s |
| **adaptive-4 (current)** | **99.2%** | **136/137** | **6.5 s** | 18.4 s |
| reference ("a person") | 98.0% | 128/137 | 31.1 s | 56.6 s |

The one page below 95% (xdcam-user.com) is a bot challenge the browser met and plain HTTP didn't; the service keeps
the plain response there. By label: app-shell pages go from 12% (HTTP) to 100%, partial pages from 68% to 100%,
accepted pages from 84% to 98%.

Findings that shaped the renderer:

- Google-style tall viewport alone adds nothing (78% vs 77%); scrolling screen by screen is what loads lists.
- Waiting for network idle wastes time: busy sites never go idle; wait for content growth instead.
- Blocking images/fonts halves the download with no content loss.
- Headless browsers got a Cloudflare challenge on ~4% of pages where the plain fetch got content: never downgrade.
- Pages labelled complete miss a median 2.9% of rendered content (mostly consent banners), but a tail of pages
  that look complete in raw HTML are not (att.com, an AV Club article, imo.im).
- Rotating content (live counters, randomised modules) makes a few points of coverage noise unavoidable.

## Random web (`data/random_web_urls.txt`)

259 random pages from Tranco domains across popularity bands: homepages plus one deep link per site. Each captured
with JavaScript off, with the adaptive renderer and with the reference; "content" = what both browser captures saw.
Pages where the headless browser got a bot challenge but plain HTTP didn't (16, ~7%) are set aside: they say
nothing about render need, and they are why the service never downgrades to a challenged render.

| Share of the rendered content plain HTTP already had | Pages (of 210) | Raw-HTML classifier escalated |
|---|---|---|
| ≥95% (rendering adds nothing) | 95 (45%) | 9 |
| 80–95% | 54 (26%) | 14 |
| 50–80% (rendering matters) | 30 (14%) | 9 |
| under 50% (rendering essential) | 31 (15%) | 17 |

- Rendering matters on ~29% of pages (deep pages 36/105, homepages 25/105).
- The raw-HTML classifier caught 43% of those, and half its escalations weren't needed. Hence: render by default,
  and skip only on evidence (method cache).
- Adaptive renderer on the random web: median 7.7 s, p90 14.8 s.


## HTTP-vs-render comparison (`benchmarks/comparison.py`)

Calibrates the check that decides when the plain response is enough (`compare.coverage` ≥
`sufficient_coverage`). 1,538 URLs on 1,349 sites (`data/comparison_calibration_urls.txt`), each fetched over plain
HTTP and rendered twice by the production renderer; 1,374 comparable (the rest: empty or challenged renders, non-200).

- **Noise floor:** two renders of the same page differ by median 0.0%, p75 0.1%, p90 6.5% of their content. The two
  renders give the same verdict at 95% on 98% of pages.
- **Truth** = the plain response's coverage of the content both renders saw. It holds ≥95% on 58% of pages
  (≥98% on 48%), under 80% on 24%.

| Threshold | Pages skipping the browser | Approved but truly <95% | Approved but truly <98% | Needless renders (truth ≥95%) | Content lost on approved pages (mean / p95 / max) |
|---|---|---|---|---|---|
| 90% | 64.9% | 110 | 240 | 10 | 1.6% / 7.3% / 9.9% |
| 93% | 60.5% | 56 | 182 | 17 | 1.1% / 5.4% / 6.9% |
| **95%** | **55.5%** | **0** | 122 | 29 | **0.8% / 3.8% / 5.0%** |
| 98% | 45.5% | 0 | 0 | 167 | 0.3% / 1.3% / 2.0% |

95% is kept: it approves no page that truly holds less than 95%, loses at most 5% of a page's content, and lets 55%
of pages skip rendering once the method cache has evidence for them. (Measured with `compare.http_windows`, exactly
the function production uses.) 98% would cost 10 more percentage points of
renders to recover about half a percent of content on average.

## Challenge resolution (`benchmarks/challenge.py`)

84 pages labelled bot-protected (`data/challenge_benchmark_urls.tsv`: 32 block pages and 50 sampled challenges from
`data/labels.csv`, plus Crunchbase and blackstone.com), full captures with `resolve_bot_challenges`, challenge tier
= Browserless BrowserQL (`/stealth/bql`, residential proxy, San Francisco region, driven from Japan). 5 pages were
not challenged any more; 79 went to the challenge tier:

| | Challenges (46) | Block pages (33) | All (79) |
|---|---|---|---|
| captured, real content | 37 | 23 | 60 (76%) |
| a true answer from the site (404, 5xx, login wall, paywall) | 7 | 0 | 7 (9%) |
| protection held (`bot_blocked`, `bot_challenge`, `resolution_attempted: true`) | 2 | 9 | 11 (14%) |
| the provider's proxy couldn't reach the site (`browser_unavailable`) | 0 | 1 | 1 (1%) |

Challenge-tier time: median 40 s, p90 98 s (unblock 10–20 s; the rest is round trips from Japan at ~0.5 s each).
Block pages the residential proxy doesn't get past: Cloudflare WAF "you have been blocked" rules and Akamai
"Access Denied" (Home Depot, Cricinfo).

## End to end (`benchmarks/capture.py`)

300 labelled URLs (random sample of `data/labels.csv`), full production captures from Japan with our own browser
fleet, an empty method cache (so every HTML page is rendered: the slowest case) and no challenge resolution. The
expected outcome is the label's: a blocking reason → that failure, otherwise → captured.

| | Result |
|---|---|
| captured vs failed agrees with the label | **96.7%** (290/300) |
| … and with the labelled failure reason | **96.0%** (288/300) |
| labelled usable or renderable → captured | 196/205 |
| labelled blocked or broken → failed | 94/95 (92/95 before the rules review) |
| rendered pages whose plain response already held ≥95% | 101/185 (the method cache's future savings) |
| whole capture | median 5.7 s, p90 15.1 s, max 41 s |
| plain HTTP fetch | median 0.8 s, p90 2.5 s |
| browser render | median 6.8 s, p90 15.3 s |

The 12 disagreements are mostly the web having changed since labelling (4 sites now challenge pp-bot, a host
timing out, WSJ now serving plain HTTP) and judgement calls (a section URL redirected to the front page read as a
soft 404, a 418 used as a bot block, Hugging Face answering 401 for a missing repo, parked domains kept as
unverified plain responses when the render comes out empty).

CPU per capture (300 stored pages, no network): classification median 24 ms (p90 134 ms), comparison under 2 ms
(one 3 s outlier on a huge page). About 60% of classification time
is BeautifulSoup building the tree, which the comparison reuses. Network time dominates by two orders of magnitude.

## Deployed service (2026-09-30)

The end-to-end and challenge benchmarks rerun against Stolosio's `POST /v1/capture` in production (release
`a8e8b56`), so the numbers are what callers get: its Browserless fleet, fetch-proxy egress (not Japan), user agent
`StolosioBot`, and the shared Postgres method cache. The fleet was also serving Periplus's crawl at the time, and
Browserless cloud (BrowserQL, residential proxy) was the challenge tier. `--endpoint` sends each capture to the
service; a 503 capacity refusal is waited out and not counted.

```bash
uv run python benchmarks/capture.py run data/labels.csv results/deployed_capture.jsonl --endpoint http://stolosio:8411
uv run python benchmarks/challenge.py run data/challenge_benchmark_urls.tsv results/deployed_challenge.jsonl \
    --endpoint http://stolosio:8411
```

End to end, the same 300 URLs:

| | In-process (2026-09-29) | Deployed |
|---|---|---|
| captured vs failed agrees with the label | 96.7% (290/300) | 92.3% (277/300) |
| … and with the labelled failure reason | 96.0% (288/300) | 91.3% (274/300) |
| labelled usable or renderable → captured | 196/205 | 187/205 |
| labelled blocked or broken → failed | 94/95 | 90/95 |
| rendered pages whose plain response already held ≥95% | 101/185 | 90/176 |
| whole capture | median 5.7 s, p90 15.1 s | median 4.4 s, p90 13.6 s |
| browser render | median 6.8 s, p90 15.3 s | median 5.5 s, p90 13.1 s |

279 of the 300 URLs give the same result as the in-process run. The 21 that differ move both ways and are about who
is asking: 9 pages now challenge or deny `StolosioBot` from this egress, and 6 challenged or rate-limited before but
capture now. 2 were transient `unreachable` answers that captured on a retry, and 4 fail with a different code
(3 challenges now read as block pages, one 5xx). The method cache let 5 pages skip the render (the in-process run
started empty).

Challenge resolution, the same 84 pages (78 went to the challenge tier; baseline 79):

| | Challenges (47) | Block pages (31) | All (78) | Baseline (79) |
|---|---|---|---|---|
| captured, real content | 32 | 22 | 54 (69%) | 60 (76%) |
| a true answer from the site (404, 5xx, login wall, paywall) | 6 | 0 | 6 (8%) | 7 (9%) |
| rendered but still empty (`incomplete_content`) | 3 | 0 | 3 (4%) | 0 |
| protection held (`bot_blocked`, `bot_challenge`) | 5 | 7 | 12 (15%) | 11 (14%) |
| the tier couldn't load the page (`browser_unavailable`) | 1 | 2 | 3 (4%) | 1 (1%) |

Challenge-tier time: median 36 s, p90 69 s (baseline 40 s / 98 s: fewer round trips from Europe than from Japan).
66 of 84 pages agree with the baseline. The residential proxy now gets past Cricinfo and Lowe's (Akamai), and no
longer past Crunchbase and ScienceDirect, where BrowserQL's captcha solving timed out at 60 s. One run per page is
noisy here: dl.acm.org came back `incomplete_content` (the page dropped content while scrolling) and was captured in
full on a single retry.

A capture failed once with HTTP 500: a Postgres deadlock while admitting the attempt under concurrent Periplus
traffic. Periplus defers such an answer without spending an attempt, but admission should not return 500 for a
transient conflict.

## Unseen sites (`results/unknown_sites.csv`)

200 sites never labelled or used to write rules (from the calibration URL list, labelled URLs excluded), full
captures, every failure and every capture with under 120 words of plain text reviewed by hand, 2026-09-30:

- 186 captured, 14 failed. Failures that were right: 4 bot challenges (an Anubis page, three Cloudflare 403s),
  3 real 404s, 3 unreachable hosts, a rendered login wall, 2 app shells that stayed empty.
- Wrong, and fixed: a paywall on an event calendar (its structured data mixes free and paid items).
- Captured but shouldn't have been, and fixed: a domain whose plain page and render were both empty (now
  `incomplete_content`), and a Plesk "Domain Default page" (now `parked`, with Apache, nginx and cPanel defaults).
- No other false blocks among the failures and no other blocks among the small captures.
