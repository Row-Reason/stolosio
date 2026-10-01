# Architecture

## Goal and constraints

Return the content a person would receive when visiting a URL — a trustworthy document — at the lowest cost that
achieves it, or a failure that says why. The consumer is a generic public crawler that discovers new domains all
the time: nothing may depend on hand-maintained per-site configuration. Learned per-site knowledge is allowed only
as a machine-maintained cache that corrects itself (e.g. stolosio's per-domain routing with a canary share).

Wrongly accepting incomplete content (lost content) is worse than a needless render (cost). The contract is
`docs/api.md`.

## Deployment shape

- **stolosio** hosts `POST /v1/capture` (this package, behind its egress, blocklist and browser fleet) and keeps a
  simplified CDP gateway for real browser automation.
- **periplus** calls the endpoint once per URL and stores what it returns; it keeps retries, pacing, recrawl and
  storage, and drops its own CDP/Playwright capture logic and content policies.

## Components (`src/pagecapture/`)

| Module | Responsibility |
|---|---|
| `api.py` | Contract types: `CaptureRequest`, `CaptureResult` (+ `Response`, `Document`, `Failure`, `Evidence`, `Attempt`, …) and their JSON form |
| `service.py` | `CaptureService`: the escalation ladder, trust decisions, evidence |
| `failures.py` | Failure codes (category, transient) and the mapping from assessment reasons |
| `cache.py` | Method cache: where plain HTTP has proven enough (exact URL and URL pattern), `MethodPolicy` decides skips |
| `adapters.py` | What a host provides: `Fetcher` (plain HTTP) and `BrowserTier`s; defaults `HttpxFetcher`, `CdpBrowserTier` |
| `classify/` | Assessing a response with rules: `rules.py`, `classifier.py` |
| `render/` | The adaptive renderer (`adaptive.py`) and the JavaScript it runs (`scripts.py`) |
| `document.py` | A parsed response: cheap facts without parsing, text statistics in one pass |
| `labels.py` | Reason columns and their priority (`docs/labels.md`) |
| `fetch.py` | the bot identity (StolosioBot); replaying snapshot records for benchmarks |
| `config.py` | All settings |

## The ladder (`service.py`)

1. **Plain HTTP** through the host's fetcher. No response → `failed: unreachable` (network, transient), or
   `host_not_found` (network, permanent) when a resolver confirms the host doesn't exist; redirects that don't end →
   `failed: redirect_loop` (website, permanent).
2. **Classify** the response with **rules** (`classify/`), reasons in priority order: status codes, content type,
   vendor challenge headers and markup, login redirects, explicit block / parking / maintenance wording, and
   near-certain app-shell evidence (an empty framework mount, a JavaScript notice). Status, header and redirect
   checks don't parse the HTML (`document.py` parses lazily, once, with lxml). **Early exit** at the first rule
   rejection ≥ 0.9 confidence: nothing after it can change the outcome. Whether a browser would add content is not
   predicted from raw HTML: the page is rendered and compared (below), or skipped on the method cache's evidence.
   (A learned render-need model and an LLM second opinion were tried and removed: once every usable page is
   rendered they only guarded cache skips, which the size check and canary renders already guard.)
3. **Decide:**
   - blocked / broken (404, 410, 401/403, 429, 5xx, parked, paywall, geo) → `failed`, with the page as evidence;
   - a non-HTML document → `captured` (`response_body`);
   - bot challenge → **challenge resolution** if the request allows it, else `failed: bot_challenge`; a block page
     (`rules.block_page`: refuses the IP/fingerprint, no challenge to solve) → challenge resolution only when that
     tier is proxied, else `failed: bot_blocked` without a paid render;
   - looks usable → **render by default**, unless the method cache has evidence that plain HTTP is enough for this
     URL or its URL pattern (then `captured` from HTTP; a 5% canary share is rendered anyway);
   - content missing or an interstitial → **managed browser**.
4. **Render** (`render/adaptive.py`), then re-assess the rendered DOM with the rules (a single-page app can render
   a 404 or a login wall) and the renderer's own signals (still empty? placeholders still visible? content dropped
   while scrolling?):
   - trustworthy → **compare** with the plain response (text shingles, ad-network text excluded): if the plain
     response had ≥95% of the rendered content it is returned as verified exact bytes, else the rendered DOM; the
     outcome is recorded in the method cache;
   - bot challenge in the managed browser → challenge resolution if allowed; if the plain response was usable it is
     kept (headless browsers are challenged where plain fetches aren't, ~7% of random pages); else `failed:
     bot_challenge` or `bot_blocked`;
   - still empty → `failed: incomplete_content` (or the usable plain response, kept and marked unverified).

## The method cache (`cache.py`)

- **Keys:** the exact URL (host + path + sorted query), for recrawls; and the URL pattern (host + path with ids
  and slugs generalised, query parameter names only), for new pages on a known layout.
- **Entries:** comparisons, sufficient, contradictions, last seen, typical plain-response size.
- **Skip rendering when:** the exact URL's last comparison was sufficient, or the pattern has ≥3 sufficient
  comparisons and fewer than 2 contradictions; and the plain response is usable and within 0.5–2× its usual size.
- **Invalidation:** one insufficient comparison invalidates an exact URL at once, two a pattern; entries expire
  after 30 days unseen; a response that looks different (status, classification, size) is rendered regardless.
- **Storage:** an interface (`get`/`put`); in memory by default, SQLite via `PAGECAPTURE_METHOD_CACHE`, and in
  stolosio next to its per-domain evidence.
- **Side effect:** every comparison is a labelled example of "did plain HTTP have it all?" — the training data a
  better classifier needs.

## The adaptive renderer

- Load until the HTML is parsed, then wait on the page's own activity: a DOM-change counter (installed before the
  page's scripts) and the requests in flight. A page with no DOM changes and nothing loading for 0.3 s is settled;
  a busy page whose trackers never go quiet is settled when its content stops growing. Snapshots are taken only
  when the DOM changed, and send only lines not reported before.
- Pages still nearly empty, with an empty app container, or whose main content or h1 still shows a text
  placeholder ("Loading...", in several languages) are apps still starting: keep waiting while content arrives.
- Close obvious consent dialogs with reject / necessary-only (never "accept all").
- Scroll a screen at a time to the bottom — the window, or the inner panel that scrolls — crossing empty stretches
  with a 10-screen window; give late sections a moment at the bottom; one last wait for visible placeholders.
- Block images, media and fonts; collect content across snapshots (virtualized lists); log what each step added.

## Design principles

- **Rules where they're exact; measure instead of predicting** where judgement is needed (render and compare).
- **Stop as soon as the outcome is certain**, and prove it: the classification benchmark runs fast and full mode
  and requires identical outcomes.
- **Decide from what the page is doing**, not from site lists: content growth, emptiness, scroll yield.
- **Trustworthy or failed**: uncertainty costs a render, never correctness; failures always carry evidence.
- **Every step logs what it added**: the data a learned render policy would train on.
- **Honest benchmarks**: rules scored on audited labels; rendering measured against a generous reference capture;
  end-to-end captures scored against labels.

## Known limits and next steps

- Every uncached HTML page is rendered. A predictor of "will plain HTTP hold ≥95% of the render?", trained on the
  recorded comparisons (`results/comparison.jsonl`, the `comparison` field of every capture), could skip renders on
  pages the cache hasn't seen yet.
- Virtualized lists: the final DOM can hold less than was shown (noted in evidence).
- Challenge resolution is only a tier hook here; which provider resolves challenges is the host's choice. That tier
  keeps the provider's own browser identity (no bot user agent): its stealth fingerprint is what gets it through.
  Two kinds of challenge tier:
  - **BrowserQL** (`https://…/stealth/bql?token=…&proxy=residential`, `adapters.BqlBrowserTier`): Browserless
    navigates, solves any challenge on its side (5–15 s) and hands the browser over; the renderer continues on that
    page without navigating again. Preferred: a solver behind a plain CDP session took 30–130 s or froze. Images,
    media and fonts are blocked by BrowserQL's `reject` during Browserless's load and by the renderer's request
    interception after the handover (the solver is done by then). The residential exit is pinned to
    `proxy_country` (default `jp`, matching our own fleet), else sites localise (sephora.com → sephora.fr).
  - **plain CDP** (`wss://…`, `adapters.CdpBrowserTier`): the renderer waits (up to `challenge_resolution_wait_s`,
    60 s) for a challenge to clear before its first snapshot.
    Request interception would stall its in-session solver, so this tier blocks with Chrome's URL blocklist, which
    needs CDP network events; those flood Playwright's driver on heavy pages (a crash was seen at 9 MB), one more
    reason to prefer BrowserQL.
  A Playwright driver that dies (an assertion on frames attaching during a handover was seen) is restarted and
  the render retried once; captures sharing it would otherwise all fail.

  Remote browsers can be far away (Browserless from Japan: ~0.5 s per call, ~25 KB/s for large messages, and a
  timed-out message keeps streaming and blocks every call behind it). So every in-page call is time-bounded and a
  page that stops answering (`PageBusy`) ends exploration with what it has; large results are gzipped in the page
  and moved in 48 KB slices; the final DOM is read at the end of the render, while the page is known to respond;
  snapshots back off in proportion to their own cost; renders stop fetching after `max_transfer_mb` (20 MB).
  Whether it egresses through proxies (`proxied`) decides whether block pages are worth an attempt.
- Per-domain starting tier (skip HTTP for domains that always need a browser) belongs to the host's routing.
- Ad text is excluded from the comparison by a list of ad-network vendor names (`render/scripts.py`); unknown
  networks just cost renders. Recommendation widgets count as content (per `docs/labels.md`), so sites with them
  keep being rendered.
