# Page capture

`POST /v1/capture` answers "give me this page": the page's content as a person would receive it, at
the lowest cost that achieves it, or a failure that says why. The algorithm and its contract live in
the `pagecapture` workspace package ([contract](../packages/pagecapture/docs/api.md), JSON examples in
[`contract/`](../packages/pagecapture/contract)). Stolosio hosts it on its own capacity, egress and
network policy. `WS /v1/connect` stays the endpoint for real browser automation.

```http
POST /v1/capture
Content-Type: application/json

{"url": "https://example.com/", "accept": ["text/html"], "exclusions": [{"host": "*.ads.example"}]}
```

| Status | Meaning |
| --- | --- |
| 200 | Every capture result, `captured` or `failed` |
| 400 | An invalid request, including a `url` its own exclusions cover |
| 503 + `Retry-After` | No capacity to start the capture, or a database conflict that outlasted retries; the body is a `failed` result with failure code `capacity` |

There is no authentication: the endpoint is for callers inside the deployment's network.

## Capacity

A capture is a Stolosio session that holds one slot of the local `browserless` fleet from
admission to response: plain HTTP first, then a render on that slot when needed. Captures and
`/v1/connect` sessions share the global session limit, the provider queue and its accounting. When
admission can't finish while at least 10 seconds of the capture's deadline remain, or the queue is
full, the capture is refused with 503. Admission retries a Postgres deadlock or serialization
failure a few times; one that still fails refuses the capture with 503 and detail
`database_conflict`, never 500.

## Egress and network policy

The plain fetch goes through the egress proxy (`HTTP_FETCH_PROXY_URL`) only, never the API
process's own network; the proxy's own error answers (and a refused `CONNECT`) fail the capture as
`unreachable` (transient), or as `host_not_found` (permanent) when the API's resolver confirms the
host has no such name or no address: the proxy's DNS failure alone can be a resolver hiccup. Stolosio's
network policy joins the request's exclusions, so a blocked domain is refused on every redirect hop
and for every browser request (`excluded`). Browsers enforce exclusions through the CDP Fetch
domain, which also catches redirect hops.

## Challenge resolution

A bot challenge is resolved only when the request sets `resolve_bot_challenges` and an operator has
enabled the `browserless_cloud` provider (`PATCH /v1/admin/providers/browserless_cloud/capacity`;
it needs `BROWSERLESS_CLOUD_TOKEN`). The capture then trades its local slot for a
`browserless_cloud` attempt, counted against that provider's concurrency limit, and Browserless
BrowserQL unblocks the page through a residential proxy (`BROWSERLESS_CLOUD_PROXY_COUNTRY`, default
`jp`). No cloud capacity fails the capture as `capacity` (transient).

## State and accounting

- The method cache (`capture_method_cache`) remembers, per URL and URL pattern, where rendering
  confirmed that plain HTTP is enough. It is the only thing Stolosio learns about sites; the
  maintenance worker purges entries unseen for `CAPTURE_METHOD_CACHE_RETENTION_DAYS` (30).
- Every capture writes a `capture.completed` outbox event: outcome, failure code and category,
  tiers used, duration, browser seconds, whether a paid tier was used, bytes.
- A failed capture logs a warning with its failure code, category, transience and session id;
  never the URL or the failure message, which may carry credentials.
- Metrics: `stolosio_captures_total{outcome,category}`, `stolosio_capture_rejected_total{reason}`,
  `stolosio_capture_duration_seconds{tier}`, `stolosio_capture_browser_seconds_total{tier}`,
  `stolosio_capture_paid_total`.
