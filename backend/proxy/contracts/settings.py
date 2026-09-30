from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from backend.proxy.contracts.provider import ProviderName


class SettingSource(StrEnum):
    EXPLICIT = "explicit"
    DEFAULT = "default"
    POLICY = "policy"


class ProviderSettingSchema(BaseModel):
    slug: ProviderName = ProviderName.BROWSERLESS


class BrowserlessSettingSchema(BaseModel):
    # Residential exit country for browserless_cloud (ISO 3166-1 alpha-2); default: Stolosio's
    # setting.
    proxy_country: str | None = Field(default=None, pattern=r"^[a-z]{2}$")


class SessionSettingSchema(BaseModel):
    reference: UUID | None = None
    admission_timeout_ms: int | None = Field(default=None, ge=1, le=60_000)


@dataclass(frozen=True, slots=True)
class RequestedSessionSettings:
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def session_reference(self) -> UUID | None:
        value = self.overrides.get("stolosio.session.reference")
        return value if isinstance(value, UUID) else None


@dataclass(frozen=True, slots=True)
class ResolvedSessionSettings:
    provider: ProviderSettingSchema
    session: SessionSettingSchema
    sources: dict[str, SettingSource]
    browserless: BrowserlessSettingSchema = field(default_factory=BrowserlessSettingSchema)
    blocked_domain_patterns: tuple[str, ...] = ()
    network_policy_version: int = 1
