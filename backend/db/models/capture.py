from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


class CaptureMethodCacheEntry(Base):
    """pagecapture's method cache: per URL and URL pattern, whether plain HTTP proved enough. The
    evidence for selecting the acquisition method, separate from shared pacing."""

    __tablename__ = "capture_method_cache"
    __table_args__ = (Index("ix_capture_method_cache_last_seen", "last_seen"),)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    entry: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CaptureResultRecord(Base):
    """Compact acquisition facts, independent of debug-event retention."""

    __tablename__ = "capture_results"
    __table_args__ = (
        CheckConstraint(
            "acquisition_outcome IN ('default', 'internally_resolved', "
            "'externally_resolved', 'total_failure')"
        ),
        Index("ix_capture_results_completed_at", "completed_at"),
    )
    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acquisition_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    challenge_detected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    local_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    external_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    local_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    external_seconds: Mapped[float] = mapped_column(Float, nullable=False)
