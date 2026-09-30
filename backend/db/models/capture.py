from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


class CaptureMethodCacheEntry(Base):
    """pagecapture's method cache: per URL and URL pattern, whether plain HTTP proved enough. The
    only thing Stolosio remembers about sites."""

    __tablename__ = "capture_method_cache"
    __table_args__ = (Index("ix_capture_method_cache_last_seen", "last_seen"),)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    entry: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
