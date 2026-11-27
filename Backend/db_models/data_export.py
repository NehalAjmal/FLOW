from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from db_models.base import Base


class DataExport(Base):
    """A copy of everything FLOW stores about one user, for them to download."""
    __tablename__ = "data_exports"

    id:         Mapped[str]            = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id:    Mapped[str]            = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status:     Mapped[str]            = mapped_column(String(10), nullable=False, default="pending")   # pending | ready | failed
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), nullable=False)
    payload:    Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
