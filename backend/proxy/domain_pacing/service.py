"""Hostname normalization and the public domain-admission boundary."""

import ipaddress

from backend.proxy.domain_pacing.contracts import Lease, Observation
from backend.proxy.domain_pacing.repository import PacingRepository


def normalize_hostname(hostname: str) -> str:
    value = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        pass
    if not value or len(value) > 253:
        raise ValueError("Invalid hostname")
    for label in value.split("."):
        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(
                character.isascii() and (character.isalnum() or character == "-")
                for character in label
            )
        ):
            raise ValueError("Invalid hostname")
    return value


class DomainPacing:
    def __init__(self, repository: PacingRepository) -> None:
        self.repository = repository

    async def acquire(
        self, hostname: str, session_id: str, lease_seconds: float, *, lease_id: str | None = None
    ) -> Lease:
        return await self.repository.acquire(
            normalize_hostname(hostname), session_id, lease_seconds, lease_id=lease_id
        )

    async def release(self, lease: Lease, observation: Observation | None = None) -> None:
        # Observation and release share one transaction: retries cannot count a sample twice.
        await self.repository.release(lease, observation)
