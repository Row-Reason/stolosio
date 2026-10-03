---
title: Observe & troubleshoot
description: Inspect sessions, understand DEBUG observations, and diagnose deployment problems.
---

## Start with the admin interface

Overview gives browser automation and page capture equal prominence. Use Sessions to inspect CDP connections, command outcomes, and provider attempts. Use Captures to inspect HTTP-only completions, local rendering, challenge resolution, failure codes, and acquisition timelines. Both histories support filtering and pagination.

HTTP-only counts pages acquired without a browser attempt, as a share of successful captures. A browser render that verifies the original HTTP response still counts as browser use. HTTP-only captures also reserve local browser capacity, so browser execution and occupied capacity are shown separately.

Capacity shows queue pressure and fleet readiness. Settings manages policy and rates. Usage can show both workloads or either one separately; its costs are modeled observations, not provider invoices. Events provides the retained and live activity feed for deeper investigation. Normal session closure describes the connection rather than the success of the caller’s automation task.

DEBUG events describe what happened. They do not diagnose a challenge, prescribe another provider, or recommend IP rotation.

## Correlate a single session

Generate a UUID and use the same reference on both connections:

```text
ws://localhost:8411/v1/connect?stolosio.session.reference=<uuid>
ws://localhost:8411/v1/debug?stolosio.session.reference=<uuid>
```

The DEBUG WebSocket can connect first and wait up to 30 seconds for the reference. It replays retained events for that session and then follows the live stream. Each text frame contains a canonical session event. The connection closes after session termination.

The UUID is not an access credential. A slow DEBUG consumer can be disconnected with `debug_consumer_too_slow`; it does not slow browser execution. See the [event contract](https://github.com/elei-io/stolosio/blob/main/docs/DEBUG.md) for retention and delivery details.

## Local diagnostics

```bash
docker compose ps
docker compose logs --tail=100
curl http://localhost:8411/health
```

The API health response reports NATS and JetStream state. A healthy API response alone does not prove browser capacity is ready; also inspect the fleet and run a client session.

## Common symptoms

| Symptom                              | Check next                                                                                                  |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| Connection refused                   | Verify the API process, published port, and client URL.                                                     |
| Browser acquisition stays queued     | Check the controller process, ready slots, maximum instances, and provider queue limits.                    |
| Browserless cloud session is refused | Check the token, enabled provider capacity, and its active-session and queue limits.                        |
| Browser connection closes early      | Inspect the recorded reason and provider session timeout. Do not assume every disconnect is a client error. |
| Activity feed is unavailable         | Check NATS and JetStream connectivity and the maintenance worker. PostgreSQL remains authoritative.         |
| Kubernetes workers are not Ready     | Inspect Pod events, image-pull access, architecture, resources, and probe failures.                         |

## Metrics

The API exposes `/metrics`. The Docker fleet controller exposes its metrics at `http://localhost:9101/metrics` by default. Scrape only through your trusted monitoring network.

Provider-and-method summaries include counts, failures, timing, and attributed costs where available. Use them alongside acquisition outcomes; low cost alone does not demonstrate correct content retrieval.
