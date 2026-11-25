from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from db_models.base import Base


class Rating(Base):
    """A 1-5 self-report: how focused / tired the user feels, e.g. before and after a break."""
    __tablename__ = "ratings"

    id:         Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id:    Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)

    kind:       Mapped[str]           = mapped_column(String(20), nullable=False)   # focus | fatigue | post_break_focus
    value:      Mapped[int]           = mapped_column(Integer, nullable=False)      # 1..5
    context_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)    # e.g. the break id
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False)
