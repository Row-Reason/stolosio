# Stolosio Vision

Stolosio is a personal browser and web-acquisition fleet. It gives automation clients a
single endpoint through which they can acquire, use, observe, and release browser
sessions without coupling themselves to a particular browser implementation or runtime
platform.

## Product promise

Stolosio aims to be a CDP-compatible browser gateway:

> Change the browser endpoint, retain the automation, and gain fleet management and
> observability.

A client already using Puppeteer, a CDP library, or Playwright's `connect_over_cdp()`
should be able to replace its browser URL with a Stolosio URL and continue using its
existing automation. The provider can then be changed through the URL:

```text
wss://stolosio.example/v1/connect
wss://stolosio.example/v1/connect?stolosio.provider.slug=browserless
wss://stolosio.example/v1/connect?stolosio.provider.slug=browserless_cloud
```

Clients that only need a page's content use `POST /v1/capture`, which chooses between
plain HTTP and a browser render by itself.

Stolosio will target the common 80 percent of browser automation behavior across all
providers. Provider-specific and uncommon commands may not work everywhere initially,
but unsupported behavior must fail explicitly and predictably rather than hang or
silently produce an incorrect result.

Native browser providers relay CDP without method-by-method mappings.

## Initial providers

Stolosio begins with two browser providers:

- Browserless provides native CDP through a Stolosio-managed, horizontally scalable
  fleet with explicit per-instance session capacity. It is the default.
- Browserless cloud provides native CDP through paid, externally managed stealth
  browsers behind residential proxies, with Stolosio-owned concurrency and queue
  limits. Clients select it explicitly when a task requires it.

Page capture adds plain HTTP retrieval through Stolosio's egress proxy, rendering only
when HTTP is not enough.

## Initial scope

Stolosio will:

- Provide clients with isolated browser sessions.
- Connect sessions to the provider they name, defaulting to the managed fleet.
- Pack isolated sessions into compatible browser instances and scale managed provider
  fleets from measured demand.
- Expose per-provider demand, capacity, health, and scaling metrics.
- Preserve opaque native CDP passthrough for browser providers.
- Own session authentication, authorization, lifecycle, and cleanup.

Browser processes are local Docker Compose dependencies during development. Stolosio
owns their desired capacity, placement, health, and draining through a separate fleet
controller. Docker, Kubernetes, or another runtime supplies the compute primitives.

## Longer-term direction

Stolosio will later:

- Learn to optimize browser placement and resource usage from historical data.
- Provide a standardized live debugging stream across providers.
- Provide a web interface for fleet monitoring and session debugging.
- Make provider compatibility, cost, and scaling behavior observable over time.

## Design principles

### Adoption without rewrites

Existing CDP automation should require an endpoint change, not a new automation SDK.

### Honest portability

Stolosio exposes capabilities and explicit protocol errors. It does not pretend that a
provider supports behavior that cannot be implemented faithfully.

### Progressive compatibility

Compatibility expands domain by domain and command by command. Native CDP providers
use passthrough only for explicitly verified methods; translated providers begin with
high-value operations and grow from observed usage.

### Managed fleets

Stolosio owns browser fleet policy without embedding infrastructure credentials in the
gateway. Separate controllers reconcile Stolosio's desired state through Docker,
Kubernetes, or another platform. Administrators control fleet limits; downstream
clients remain unaware of browser instances and capacity.
