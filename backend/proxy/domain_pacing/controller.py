"""Pure feedback rules. No database, capture implementation or transport dependencies."""

import math
from dataclasses import replace
from datetime import datetime, timedelta

from backend.proxy.domain_pacing.contracts import Observation, PacingSettings, Policy


def reset(settings: PacingSettings, policy: Policy, now: datetime) -> Policy:
    return Policy(
        concurrency=settings.default_concurrency,
        spacing_seconds=settings.default_spacing_seconds,
        expires_at=now + timedelta(seconds=settings.learned_ttl_seconds),
        cooldown_until=policy.cooldown_until,
        generation=policy.generation + 1,
        reason="ttl_expired",
        adjusted_at=now,
    )


def update(
    settings: PacingSettings,
    policy: Policy,
    observation: Observation,
    now: datetime,
    *,
    at_limit: bool,
    concurrency_at_limit: bool,
    generation: int,
) -> Policy:
    if observation.outcome == "neutral":
        return policy
    if observation.outcome == "overload" and generation != policy.generation:
        return policy
    # Failures remain relevant after another in-flight capture changed the allowance;
    # old successes must never undo a backoff or count towards a new increase.
    if observation.outcome == "healthy":
        if generation != policy.generation or (
            policy.cooldown_until and now < policy.cooldown_until
        ):
            return policy
        policy = replace(policy, overload_samples=0)
        if not at_limit:
            return policy
        policy = replace(
            policy,
            healthy_samples=policy.healthy_samples + 1,
            concurrency_samples=policy.concurrency_samples + int(concurrency_at_limit),
            expires_at=now + timedelta(seconds=settings.learned_ttl_seconds),
        )
        if policy.healthy_samples < settings.healthy_samples:
            return policy
        concurrency, spacing = policy.concurrency, policy.spacing_seconds
        if (
            policy.concurrency_samples >= settings.healthy_samples // 2
            and concurrency < settings.maximum_concurrency
        ):
            concurrency = min(settings.maximum_concurrency, concurrency + 1)
        else:
            spacing = max(settings.minimum_spacing_seconds, round(spacing * 0.9, 6))
        changed = concurrency != policy.concurrency or spacing != policy.spacing_seconds
        return replace(
            policy,
            concurrency=concurrency,
            spacing_seconds=spacing,
            healthy_samples=0,
            concurrency_samples=0,
            generation=policy.generation + int(changed),
            reason="healthy_at_limit" if changed else policy.reason,
            adjusted_at=now if changed else policy.adjusted_at,
        )
    count = policy.overload_samples + 1
    if observation.outcome == "overload" and count < settings.overload_samples:
        return replace(policy, overload_samples=count, healthy_samples=0, concurrency_samples=0)
    retry = observation.retry_after_seconds
    if retry is None or not math.isfinite(retry) or retry < 0:
        retry = settings.cooldown_seconds
    cooldown = now + timedelta(seconds=min(retry, 31536000))
    if policy.cooldown_until is not None:
        cooldown = max(cooldown, policy.cooldown_until)
    if generation != policy.generation:
        # One burst should cause one reduction. Older explicit refusals can still extend a cooldown.
        if observation.outcome != "throttled" or cooldown == policy.cooldown_until:
            return policy
        return replace(
            policy,
            cooldown_until=cooldown,
            generation=policy.generation + 1,
            reason="origin_throttled",
            adjusted_at=now,
        )
    return replace(
        policy,
        concurrency=max(1, policy.concurrency // 2),
        spacing_seconds=min(settings.maximum_spacing_seconds, policy.spacing_seconds * 2),
        cooldown_until=cooldown,
        expires_at=now + timedelta(seconds=settings.learned_ttl_seconds),
        healthy_samples=0,
        concurrency_samples=0,
        overload_samples=0,
        generation=policy.generation + 1,
        reason="origin_throttled" if observation.outcome == "throttled" else "origin_overload",
        adjusted_at=now,
    )
