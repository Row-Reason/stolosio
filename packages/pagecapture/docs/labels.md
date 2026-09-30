# Labels (data/labels.csv)

Hand-verified corpus. Labels are judged only from the plain HTTP response (status, headers, redirects, returned body), never from a JavaScript-rendered page. Responses were fetched as pp-bot (the user agent in the scripts) from a Japanese IP on 2026-09-29 and are stored in `data/snapshot.jsonl.gz`; labels describe those stored responses. Sites change within hours, so a live re-fetch can differ.

| Column | Meaning |
|---|---|
| `url` | The URL the request was made to. |
| `_rejected` | `true` when any reason column below is `true`: a crawler can't use the response as page content as it is. |
| `_<reason>` | One boolean per reason below. Each is judged on its own, so several can be `true` at once. |

| Column | `true` when | Typical crawler action |
|---|---|---|
| `_unreachable` | No HTTP response: DNS failure, refused/reset connection, TLS error, timeout, redirect loop. All other columns are then `false`. | Retry later; drop after repeated failures |
| `_payload_mismatch` | A successful (2xx/3xx) response whose body is not HTML/XML (PDF, JSON, image, plain text, binary, empty). Never for error statuses. | Route to another parser or drop |
| `_bot_challenge` | A bot challenge, captcha or bot/"access denied" block page instead of the real page. | Real browser/proxy, or skip |
| `_rate_limited` | HTTP 429, or the page says too many requests were sent. | Back off, retry later |
| `_geo_blocked` | HTTP 451, or the page says the site or content is unavailable in the requester's country/region. | Retry from another region |
| `_unsupported_browser` | The page says the browser/client is unsupported or outdated (user-agent check). | Retry with another user agent |
| `_interstitial` | A page in front of the real one: consent wall, queue/waiting room, redirect stub, region/language picker, cookies-required page, frameset. | Follow through or accept, then retry |
| `_auth` | A login wall, or the request redirects to a login/sign-up page. | Needs credentials, or skip |
| `_paywall` | HTTP 402 (pay-per-crawl), or content withheld behind payment (article cut short for subscribers). | Needs subscription/payment, or skip |
| `_parked` | Parked or for-sale domain, a registrar's "coming soon" placeholder, or an empty server default (bare directory listing, web-server welcome page) instead of a site. | Drop the domain |
| `_gone` | HTTP 410, or the page says the resource was deleted/removed/is no longer available. | Drop the URL permanently |
| `_not_found` | HTTP 404, or a soft 404: a "not found" page with another status, or a deep link redirected to a front page. | Drop the URL (optionally recheck later) |
| `_client_error` | Any 4xx status other than 402, 404, 410 and 429 (400, 401, 403, 405, 414, 422, 451, …), whatever the page says. | Check the URL/request; don't retry as-is |
| `_server_error` | Any 5xx status, or a maintenance/downtime page. | Retry later (honour `Retry-After`) |
| `_app_shell` | The page's own main content is missing from the HTML and would only appear after JavaScript runs. | Render with a browser |
| `_partial` | Some of the page's content is in the HTML, but a browser would show more relevant content that JavaScript fills in (details below). | Render with a browser |

`_app_shell` and `_partial` describe the page as served, whatever it is: a 404 page that is an empty shell is both `_not_found` and `_app_shell`; a paywalled article whose teaser loads by JavaScript can be `_paywall` and `_partial`. For challenge, interstitial and parked pages the page's own content is the block itself, so they are not `_app_shell` or `_partial` because of their challenge scripts.

`_partial` in practice: the question is whether a browser would give the crawler relevant content that plain HTTP doesn't. It is `true` when, after the page loads in a browser (anonymous visitor, no clicks), visible content would be there that the raw HTML lacks because JavaScript fills it in, and the raw HTML shows that gap (skeleton/loading markup, "Loading…" text, empty lists, grids, tables or web components, unfilled values such as `0`/`--`/`xxxx` counters and prices). Any content counts: sections, lists, tables, reviews, comments, related or recommended items, prices, counters, scores. It doesn't count when a browser adds no information on load: ads and sponsored slots; UI that only fills on interaction (cart, search suggestions, menus, closed modals, chat widgets, other tabs, "load more" or further infinite-scroll pages); spinners in buttons; lazy-loading images whose text is present; iframes and media embeds (video players, maps), whose content is a separate document; content shown only to logged-in users; widgets that depend on the visitor rather than the page (weather, "near you" or location-based listings, recently viewed, the visitor's own network info). A search page opened without a query isn't `_partial`: it has no results to show. Content counts as present when its text is anywhere in the HTML body, even in a hidden element that JavaScript later swaps in (streamed server rendering puts the real content in hidden segments after a skeleton); text that exists only inside scripts, JSON or attributes doesn't count. Pages whose missing sections leave no trace in the HTML can't be labelled from raw HTML; they can only be found by comparing with a render.

The checkers return one primary reason: the first `true` column in the table order above (e.g. a 403 challenge page is `_bot_challenge` and `_client_error`, primary `bot_challenge`). `benchmarks/classify.py` derives it from the columns the same way.

When unsure, prefer rejecting: a page wrongly sent to a browser only costs a render, a page wrongly accepted loses content.

Crawl policy (robots.txt, `noindex`, `X-Robots-Tag`) is a separate check and not a reason: a `noindex` page can still be perfectly usable HTML.
