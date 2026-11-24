from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from db_models.base import Base


class UserSettings(Base):
    """One row per user. Task 4 (settings) adds more columns here later."""
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    timezone:     Mapped[str]                = mapped_column(String(64), nullable=False, default="UTC")  # e.g. Asia/Kolkata
    quiet_start:  Mapped[Optional[str]]      = mapped_column(String(5), nullable=True)                   # "22:00"
    quiet_end:    Mapped[Optional[str]]      = mapped_column(String(5), nullable=True)                   # "07:00"
    paused_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)