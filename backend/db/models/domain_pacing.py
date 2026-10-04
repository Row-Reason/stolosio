from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


class DomainPacingSettings(Base):
    __tablename__ = "domain_pacing_settings"

    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DomainPacingState(Base):
    __tablename__ = "domain_pacing_state"
    __table_args__ = (
        CheckConstraint("concurrency >= 1 AND spacing_seconds > 0"),
        Index("ix_domain_pacing_state_expires_at", "expires_at"),
    )

    hostname: Mapped[str] = mapped_column(String(253), primary_key=True)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    spacing_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    spacing_refused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    healthy_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overload_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settings_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    adjusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DomainPacingLease(Base):
    __tablename__ = "domain_pacing_leases"
    __table_args__ = (Index("ix_domain_pacing_leases_host_expiry", "hostname", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hostname: Mapped[str] = mapped_column(
        ForeignKey("domain_pacing_state.hostname", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("gateway_sessions.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    at_limit: Mapped[bool] = mapped_column(nullable=False)
    concurrency_at_limit: Mapped[bool] = mapped_column(nullable=False)


class DomainPacingRequest(Base):
    """Admission facts without URLs or page data; retained independently of sessions."""

    __tablename__ = "domain_pacing_requests"
    __table_args__ = (
        Index("ix_domain_pacing_requests_host_started", "hostname", "started_at"),
        Index("ix_domain_pacing_requests_started", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refusal: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str | None] = mapped_column(String(16))
    active_captures: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    spacing_seconds: Mapped[float] = mapped_column(Float, nullable=False)
