from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from db_models.base import Base


class Intervention(Base):
    """One row per prompt FLOW actually showed. Task 2 fills in the response columns."""
    __tablename__ = "interventions"

    id:         Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id:    Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)

    kind:         Mapped[str]           = mapped_column(String(30), nullable=False)   # fatigue | stuck | passive | distracted | trough
    title:        Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    focus_score:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    explanation: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True
    )       # score when it was shown
    shown_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # ── Filled in by Task 2 (prompt responses) ──
    response:        Mapped[Optional[str]]      = mapped_column(String(20), nullable=True)  # accepted | dismissed | snoozed | overridden
    responded_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    snooze_until:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    override_reason: Mapped[Optional[str]]      = mapped_column(String(30), nullable=True)
    report_reason:   Mapped[Optional[str]]      = mapped_column(String(30), nullable=True)
    report_text:     Mapped[Optional[str]]      = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Intervention {self.kind} session={self.session_id[:8]} response={self.response}>"
