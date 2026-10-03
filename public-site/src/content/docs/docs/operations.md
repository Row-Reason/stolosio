---
title: Operate your fleet
description: Manage capacity, provider queues, paid capacity, cost rates, and domain blocking.
---

The protected admin interface for an installation is the operator's control surface. In local development it is available at `http://localhost:5173`.

## Understand capacity

A logical session consumes global Stolosio capacity. Acquisition attempts enter provider queues and receive browser slots. Sessions do not own a permanent provider.

Managed fleets consist of browser instances with session slots. Only healthy, ready, non-draining instances contribute available capacity. Browserless capacity is based on instances multiplied by configured session slots per instance.

## Set fleet policy

Use the admin interface to inspect and adjust fleet enablement, minimum and maximum instances, queue limits, cooldown, and per-instance concurrency.

PostgreSQL is authoritative for saved policy. Environment variables carry credentials, endpoints, and runtime mechanics; they do not reconcile or overwrite saved fleet limits. Client query parameters cannot override administrative fleet limits.

Begin with limits your host can support. Watch readiness, queue pressure, and browser memory before raising concurrency.

## Keep the controller running

The fleet controller is separate from the API. It reconciles desired browser capacity through Docker or Kubernetes. If it stops, existing sessions can continue, but scaling, replacement, and rollout pause.

In Kubernetes, scale-down drains the highest ordinal first and waits for live assignments to finish. Template replacement and session-capacity changes wait for zero demand. See the [deployment guide](/docs/kubernetes/).

## Providers are explicit

A session connects to the provider it names and stays there; without a name it uses the managed Browserless fleet. Stolosio does not route sessions between providers.

Paid Browserless cloud requires a configured token and capacity an operator has enabled on the Fleets page. It is used only when a session names it, or when a capture request asks for bot-challenge resolution. Its active-session and queue limits apply to both.

## Cost rates

Every acquisition attempt is charged for the time it holds capacity, from acquisition to release, at its provider's rate in cost units per second. Operators set the rates on the Settings page; installation defaults are 100 for `browserless` and 300 for `browserless_cloud`. The Usage page reports the resulting totals.

## Domain blocking

The same operator-managed domain blocklist, edited on the Settings page, applies to every browser attempt and every capture. It is meant for ads, trackers and similar requests. In `/v1/connect` sessions it fails a page's own requests to a listed host but does not stop navigating to one; capture also refuses those navigations, and its plain HTTP fetch checks every redirect hop. Stolosio returns `domain_blocking_unavailable` if it cannot apply the policy.

This policy does not replace network isolation. See [security](/docs/security/).
