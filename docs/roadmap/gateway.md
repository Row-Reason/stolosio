# Dependable Browser Gateway

Status: implemented

## Public contract

Stolosio exposes one provider-neutral CDP WebSocket:

```text
WS /v1/connect
```

The provider is the local `browserless` fleet unless the caller explicitly supplies
`stolosio.provider.slug`. Ordinary CDP consumers are not required to understand Stolosio's
capacity, queues, deadlines, or rejection reasons.

## Two-level admission

Stolosio separates logical downstream sessions from acquisition attempts.

```text
connection
    |
    v
global Stolosio admission
    |
    v
provider attempt admission
    |
    v
provider connection
```

Global admission limits all live Stolosio sessions. A session keeps its global slot from
admission until the downstream connection terminates.

Provider admission independently limits active and queued attempts for Browserless
and Browserless cloud. A full provider queue fails only that attempt; the gateway then
terminates and releases the logical session cleanly.

This separation also lets a page capture trade its local attempt for a Browserless
cloud attempt without changing session identity.

## Lifecycles

Logical session:

```text
requested -> admitted -> open -> closing -> closed
     |          |         |
     +----------+---------+-> failed
```

Acquisition attempt:

```text
requested -> queued -> acquiring -> active -> completed
     |          |          |          |
     +----------+----------+----------+-> failed
```

Sessions own the downstream socket, lease, requested settings, and cleanup. Attempts
own the resolved provider settings, FIFO position, provider resource, and outcome.

## Coordination and failure handling

- PostgreSQL transactions own global admission, provider admission, FIFO ordering,
  leases, and state transitions.
- NATS capacity messages only wake provider waiters; PostgreSQL polling remains the
  correctness fallback.
- The API replica that receives a WebSocket retains ownership of it. Live sockets are
  never placed on JetStream or transferred between workers.
- Downstream disconnect is watched while provider admission is pending.
- One gateway component owns accept, denial, and close behavior.
- Overload before upgrade is an ordinary HTTP service-unavailable response.
- Release is bounded and idempotent; expired leases recover capacity after replica
  failure.
- Lifecycle and attempt events are inserted transactionally into the PostgreSQL outbox.
  The maintenance worker publishes them; NATS cannot delay admission.

## Subsequent milestones

This milestone established the logical-session and acquisition-attempt boundary.
Page capture was later built on the same boundary. Registered CDP
discovery and target-management HTTP routes remain explicit placeholders.
