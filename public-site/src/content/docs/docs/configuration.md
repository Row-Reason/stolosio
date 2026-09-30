---
title: Configuration
description: Distinguish client settings, saved operator policy, and runtime configuration.
---

## Three configuration surfaces

| Surface                    | What belongs here                                                    | Where to change it                                  |
| -------------------------- | -------------------------------------------------------------------- | --------------------------------------------------- |
| Client connection settings | Provider selection, session reference, admission timeout             | `stolosio.*` query parameters on the connection URL |
| Operator policy            | Fleet bounds, provider capacity, queues, cost rates, domain blocking | Admin interface, persisted in PostgreSQL            |
| Runtime configuration      | Credentials, service endpoints, ports, process mechanics             | Environment or deployment Secrets and chart values  |

Explicit query settings override defaults. Client settings cannot override administrative capacity limits.

## Common connection settings

| Setting                                 | Purpose                                                                                                          |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `stolosio.provider.slug`                | Select `browserless` (the default) or paid `browserless_cloud`.                                                  |
| `stolosio.session.reference`            | Supply a UUID to correlate a CDP connection with the DEBUG stream.                                               |
| `stolosio.session.admission_timeout_ms` | Bound total admission and provider preparation to 1–60,000 ms. Does not limit navigation or an accepted session. |
| `stolosio.browserless.proxy_country`    | Two-letter residential exit country for `browserless_cloud` sessions.                                            |

```text
ws://localhost:8411/v1/connect?stolosio.provider.slug=browserless_cloud
```

The connection route stays `/v1/connect` for all providers. Provider addresses are internal implementation details.

## Environment configuration

Use the checked-in [`.env.example`](https://github.com/elei-io/stolosio/blob/main/.env.example) as the source for supported runtime overrides. Keep secrets in an ignored `.env` file for local development.

The admin host port is controlled by `STOLOSIO_ADMIN_PORT`. Saved fleet, capacity, cost-rate, and network policy is not overwritten from environment variables at startup.

## Helm values

Consult the [chart values](https://github.com/elei-io/stolosio/blob/main/charts/stolosio/values.yaml) for the version you deploy. The chart accepts existing database, NATS, and optional Browserless cloud Secrets. It also defines static workload settings such as images, resources, and scheduling constraints.

Stolosio's live browser replica count and concurrency are owned by its fleet controller and saved policy.

Capacity and admission-wait denials return HTTP 429 with `Retry-After: 5` before
WebSocket acceptance. Use jittered retries and allow a small margin between the
server admission budget and the client connection timeout. Provider availability
failures remain HTTP 503/504.
