# Capture domain pacing

Stolosio owns shared destination admission for `POST /v1/capture`. Downstream crawlers own
URL selection, crawl scheduling, retries, robots.txt, recrawl and storage. They should schedule
other hosts when Stolosio returns a pacing refusal.

The guarantee is **capture-level**: at most two active captures per hostname, with at least one
second between admitted starts by default. All API replicas and callers share the allowance.
There is no accumulated burst credit. A capture can make multiple HTTP, redirect, verification
and browser requests; these limits do not space individual requests or independently limit
redirected hosts. `/v1/connect` is unaffected.

Keys are lowercase IDNA hostnames without trailing dots (or normalized IP literals). Schemes,
ports, paths and callers do not partition the allowance. Subdomains remain separate; there is
no automatic domain grouping or claim that hostname matches a site's throttle scope.

## Refusals

A refusal returns HTTP **429**, integer-second `Retry-After`, and the normal capture result:
`failed`, no document, failure `domain_throttled`, category `gateway`, transient true, and matching
`failure.retry_after_seconds`. Reasons are bounded values:

- `domain_spacing`: the next capture cannot start yet.
- `domain_concurrency`: every allowed capture slot is occupied.
- `domain_cooldown`: origin throttling or repeated overload activated a cooldown.

No destination request or provider acquisition occurs for a pacing refusal. Logical session
capacity is released and its terminal reason is retained. Concurrency retry guidance is a polling
estimate capped at five seconds, not a reserved start time. Target HTTP 429 remains a completed
capture result (HTTP 200, website `rate_limited`). Global capacity refusals remain HTTP 503.

## Module and persistence

`backend/proxy/domain_pacing/` contains typed contracts, a pure feedback controller, PostgreSQL
transactions and a small admission service. `backend/proxy/capture/pacing.py` converts capture
results into typed observations. The pacing module does not depend on pagecapture. The runner
acquires before acquisition and observes and releases in one transaction. FastAPI translates
refusals into transport responses.

- `domain_pacing_settings`: operator settings and version; defaults seed missing rows only.
- `domain_pacing_state`: allowance, TTL, cooldown, next start, learning counters and generation.
- `domain_pacing_leases`: active captures with bounded expiry for crash recovery.

Admission locks the hostname row and reads PostgreSQL's clock after locking. No transaction
stays open during acquisition. Expired leases stop counting; duplicate observations/releases
are harmless. Lease expiry exceeds the remaining capture deadline. Cancellation drains late
admissions. Database errors never bypass pacing, and admission never waits for NATS.

## Learning

- Origin `rate_limited`: immediately halve concurrency (minimum one), double spacing (within
  the configured bound), and apply origin retry guidance or the 30-second default cooldown.
- Three observed origin `website_error`, `access_denied` (HTTP 401/403) or `bot_blocked` results
  without an intervening healthy result: the same backoff. Origins often block a crawl with
  403s rather than 429s; an isolated denied page is broken up by healthy results and does not
  back off. Provider capacity, network/proxy failures, deadlines, missing pages, bot challenges
  and other website failures are neutral.
- Ten healthy samples near the allowance by default: increase concurrency by one if at least half
  exercised its concurrency limit and concurrency can still increase; otherwise reduce spacing
  by 20%. One control changes at a time. Default learning bounds are eight concurrent captures
  and 0.1-second spacing.
- Sparse traffic does not raise limits or renew TTL. Near-limit healthy evidence and backoff
  renew the allowance for 24 hours. TTL expiry resets limits and counters to defaults, preserving
  active cooldowns, leases and reserved next-start times.
- Policy generations stop old successes from undoing backoff. Older explicit refusals may
  extend a cooldown, but do not repeatedly halve limits for the same in-flight burst.

With the default threshold and spacing step, sustained qualifying spacing pressure lowers
one-second spacing to the 0.1-second floor in 110 samples. Saved operator thresholds remain
authoritative; changing the code default does not overwrite an existing 20-sample setting.

A trustworthy successful capture is healthy evidence. Rate pressure means consecutive starts
within 1.5 times the current spacing or a recent spacing refusal (within the greater of two
seconds and 1.5 times spacing). Refusal evidence is consumed by the next admission, so client
retry rounding cannot hide unmet demand. Concurrency pressure means occupying the last permitted
slot alongside another active capture, or a concurrency refusal proves waiting demand.
Occupying a single slot alone is not evidence of pressure. Results redirected to another
hostname are neutral. No synthetic learning requests run.

Latency-driven control is deferred: total capture duration includes provider waits, rendering
and solvers. This controller learns a bounded operating allowance, not a proven site maximum
or fair allocation between customers.

## Operator controls and observations

Admin Settings contains global controls. Captures → Domain pacing (`/captures/pacing`)
contains host traffic and learned-state inspection. API endpoints:

```text
GET /v1/admin/domain-pacing/settings
PUT /v1/admin/domain-pacing/settings
GET /v1/admin/domain-pacing?hostname=example.com&limit=100
GET /v1/admin/domain-pacing/dashboard?window=1h&hostname=example.com
POST /v1/admin/domain-pacing/reset?hostname=example.com
```

Settings PUT replaces configuration and validates defaults against bounds. Saved values are
never reconciled from environment variables. Configuration changes reset allowances on their
next admission or observation, preserving leases/cooldowns. State reads show stored and effective
limits, including expired entries. Lists are bounded to 500 entries, with exact-host filtering.

Policy changes write `capture.pacing_adjusted` to the lifecycle outbox in the same transaction.
The event records normalized hostname, applied limits, generation and bounded reason; no URL,
headers, credentials, document or free text. These are facts about changes, not recommendations.
Rejection metrics use bounded reasons, never hostname labels. Maintenance removes expired state
only after cooldown and next-start expiry and when no unexpired leases remain.


### Dashboard evidence

The dashboard supports 1-hour, 24-hour and 7-day windows. The overview shows active hosts,
Stolosio-throttled hosts, current cooldowns and target throttling results. The bounded host
list (500 entries) shows average offered/admitted rates, occupied/allowed slots, spacing,
controller state and last adjustment. Filtering searches that displayed set. Host pages show
traffic and refusal charts, sampled occupancy/allowance, spacing, target response signals,
mean capture slot duration, learning counters, TTL and up to 100 retained policy changes.
The UI never claims to have discovered a site's maximum or reached equilibrium.

`domain_pacing_requests` stores one compact fact in the admission transaction: opaque lease
ID, normalized hostname, timestamp, refusal reason, occupied slots and applied limits.
Admitted captures update completion time and controller outcome in the release transaction.
Duplicate releases do not overwrite completion evidence. No URLs, page content or request
headers are retained. Seven-day traffic retention runs in bounded maintenance batches and
is independent of learned-policy and session retention. Existing traffic is not backfilled;
the dashboard reports its earliest retained measurement and leaves unsampled limits empty.

Demand includes API retries, but excludes global admission failures before the pacing module.
Start rates use admission timestamps; target signals and duration use completion timestamps,
so captures started before the window can still contribute completion evidence. Occupancy
charts show the peak **sampled at admission decisions**, not a continuous measurement.
Allowance charts show the maximum observed allowance per bucket, and spacing charts show
the smallest observed setting. Capture slot duration includes provider waits and rendering;
it is not origin latency and does not drive the controller.

Reset queues a per-host reset, displayed immediately as effective starting limits. The next
admission or observed release applies it and writes an `operator_reset` adjustment to the
transactional outbox. Reset preserves active captures, cooldowns and reserved next-start times.
It cannot bypass origin backoff. Settings changes still apply lazily in the same way.
