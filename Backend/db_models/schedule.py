from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from db_models.base import Base


class Schedule(Base):
    """A repeating planned session ("Weekly review, Mon-Fri 17:40-18:20"). Times are the user's local time."""
    __tablename__ = "schedules"

    id:         Mapped[str]      = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id:    Mapped[str]      = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name:       Mapped[str]      = mapped_column(String(100), nullable=False)
    start:      Mapped[str]      = mapped_column(String(5), nullable=False)     # "17:40"
    end:        Mapped[str]      = mapped_column(String(5), nullable=False)     # "18:20"
    weekdays:   Mapped[list]     = mapped_column(JSON, nullable=False)          # [1..7], 1 = Monday
    demand:     Mapped[str]      = mapped_column(String(10), nullable=False)    # light | moderate | heavy
    enabled:    Mapped[bool]     = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
