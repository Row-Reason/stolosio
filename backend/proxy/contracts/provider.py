from collections.abc import AsyncIterator
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from backend.proxy.contracts.session import StolosioSession
    from backend.proxy.contracts.settings import ResolvedSessionSettings


class ProviderName(StrEnum):
    # The local browser fleet, and the default for /v1/connect.
    BROWSERLESS = "browserless"
    # Browserless's paid cloud (stealth browsers behind residential proxies): only when a client
    # names it, and as the capture endpoint's challenge-resolution tier.
    BROWSERLESS_CLOUD = "browserless_cloud"


ACTIVE_PROVIDERS = tuple(ProviderName)


class ProviderSession(Protocol):
    provider: ProviderName | None
    disconnect_reason: str | None

    async def send(self, message: str) -> None: ...
    def messages(self) -> AsyncIterator[str]: ...
    async def close(self) -> None: ...


class ProviderAdapter(Protocol):
    provider: ProviderName

    async def acquire(
        self,
        session: "StolosioSession",
        settings: "ResolvedSessionSettings",
    ) -> ProviderSession: ...
