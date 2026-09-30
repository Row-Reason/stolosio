---
title: Architecture
description: Understand the gateway, durable state, observation delivery, and separate fleet controller.
---

## The request path

```text
CDP client
    │ /v1/connect
    ▼
Stolosio API → admission → acquisition attempt
                                 │
                 Browserless / Browserless cloud
```

The API owns HTTP/WebSocket transport and application lifecycle. The proxy domain owns settings resolution, admission, provider adapters, session lifecycle, and protocol transport. A session connects to the provider it names, or to the managed Browserless fleet by default, and stays there.

`POST /v1/capture` shares the same admission and capacity. It chooses its own method: plain HTTP through the egress proxy when that proves enough, otherwise a render on the managed fleet.

## Durable state

PostgreSQL owns transactional admission, queues, leases, capacity, policy, and analytical projections. Concurrent requests cannot independently claim the same capacity.

Logical sessions consume global capacity. Provider queues hold acquisition attempts, not permanent sessions.

## Fleet reconciliation

A separate controller reconciles desired browser capacity onto Docker or Kubernetes. The provider adapter consumes assigned endpoints; it does not scale infrastructure.

Healthy, ready, non-draining browser instances expose session slots. Stolosio controls draining and placement while the compute platform supplies processes or Pods.

## Observations

Lifecycle events enter a transactional outbox. Admission does not wait on messaging. NATS Core carries live coordination; JetStream supports durable observation delivery and replay. PostgreSQL retains authoritative history. Stolosio has no Redis dependency.

DEBUG carries filtered facts, not diagnoses or provider recommendations.

## Contribute

Start with the [contribution guide](https://github.com/elei-io/stolosio/blob/main/CONTRIBUTING.md), [implementation guide](https://github.com/elei-io/stolosio/blob/main/AGENTS.md), and deeper [architecture document](https://github.com/elei-io/stolosio/blob/main/docs/ARCHITECTURE.md).

The public site builds independently from the API and admin interface. Its pages are static and do not connect to a live Stolosio installation.
