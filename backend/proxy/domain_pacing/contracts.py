from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PacingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default_concurrency: int = Field(default=2, ge=1, le=100)
    default_spacing_seconds: float = Field(default=1, ge=0.01, le=60)
    maximum_concurrency: int = Field(default=8, ge=1, le=100)
    minimum_spacing_seconds: float = Field(default=0.1, ge=0.01, le=60)
    maximum_spacing_seconds: float = Field(default=60, ge=0.01, le=3600)
    learned_ttl_seconds: int = Field(default=86400, ge=60, le=2592000)
    healthy_samples: int = Field(default=10, ge=2, le=1000)
    overload_samples: int = Field(default=3, ge=2, le=100)
    cooldown_seconds: int = Field(default=30, ge=1, le=3600)

    @model_validator(mode="after")
    def bounds(self) -> "PacingSettings":
        if self.default_concurrency > self.maximum_concurrency:
            raise ValueError("Default concurrency must not exceed maximum concurrency")
        if not (
            self.minimum_spacing_seconds
            <= self.default_spacing_seconds
            <= self.maximum_spacing_seconds
        ):
            raise ValueError("Default spacing must be within the spacing bounds")
        return self


@dataclass(frozen=True, slots=True)
class Policy:
    concurrency: int
    spacing_seconds: float
    expires_at: datetime
    cooldown_until: datetime | None = None
    healthy_samples: int = 0
    concurrency_samples: int = 0
    overload_samples: int = 0
    generation: int = 0
    reason: str = "default"
    adjusted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    outcome: Literal["healthy", "throttled", "overload", "neutral"]
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class Lease:
    id: str
    hostname: str


class DomainThrottled(Exception):
    def __init__(self, reason: str, retry_after_seconds: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
