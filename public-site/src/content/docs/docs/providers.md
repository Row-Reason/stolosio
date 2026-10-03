---
title: Providers & compatibility
description: Understand the native CDP browser providers and how page capture chooses its method.
---

| Provider                                | Intended role                                                          | Capacity owner                       |
| --------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------ |
| Browserless (`browserless`)             | Default provider, managed horizontal fleet                             | Stolosio instances and slots         |
| Browserless cloud (`browserless_cloud`) | Paid stealth browsers behind residential proxies, used only when named | Stolosio's configured external quota |

## Native CDP passthrough

Browserless and Browserless cloud receive opaque CDP traffic. Stolosio preserves command IDs, session IDs, event order, backpressure, and close behavior. The provider's browser determines whether an individual command is supported.

One browser attempt owns one upstream browser session. Independent sessions can occupy separate slots on the same Browserless worker.

## One provider per session

A session connects to the provider named by `stolosio.provider.slug`, or `browserless` when omitted, and never switches providers. If that provider has no capacity, admission returns an explicit error.

## Page capture

`POST /v1/capture` chooses its own method: a plain HTTP fetch through the egress proxy when that proves enough, otherwise a render on the managed fleet. A request that sets `resolve_bot_challenges` first tries a bounded local browser resolution attempt for bot protection, then may use Browserless cloud, when an operator has enabled it, to get past a bot challenge. Stolosio remembers per URL where plain HTTP was confirmed sufficient.

## Paid capacity and spend

Browserless cloud requires a configured token as well as enabled quota. Every attempt is charged its capacity-occupied time at its provider's rate, which operators set on the admin Policy page.

See [client settings](/docs/clients/) and the detailed [provider contract](https://github.com/elei-io/stolosio/blob/main/docs/PROVIDERS.md).
