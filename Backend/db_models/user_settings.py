from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from db_models.base import Base


class UserSettings(Base):
    """One row per user: everything on the Settings screen, plus pause."""
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    timezone:     Mapped[str]                = mapped_column(String(64), nullable=False, default="UTC")  # e.g. Asia/Kolkata
    quiet_start:  Mapped[Optional[str]]      = mapped_column(String(5), nullable=True)                   # "22:00"
    quiet_end:    Mapped[Optional[str]]      = mapped_column(String(5), nullable=True)                   # "07:00"
    paused_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Task 4. Existing databases: python -m migrations.add_settings_columns
    delivery_mode:    Mapped[str]            = mapped_column(String(10), nullable=False, default="advisory")  # advisory | explained | lock
    break_length_sec: Mapped[int]            = mapped_column(Integer, nullable=False, default=300)
    camera_enabled:   Mapped[bool]           = mapped_column(Boolean, nullable=False, default=True)   # only counts with camera consent
    calendar_enabled: Mapped[bool]           = mapped_column(Boolean, nullable=False, default=True)   # only counts with calendar consent
    llm_enabled:      Mapped[bool]           = mapped_column(Boolean, nullable=False, default=True)   # only counts with llm consent
    snooze_options:   Mapped[Optional[list]] = mapped_column(JSON, nullable=True)                     # minutes, e.g. [5, 10, 15]
