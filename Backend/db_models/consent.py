import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db_models.base import Base


class ConsentGrant(Base):
    __tablename__ = "consent_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)  # behavior | camera | calendar | llm | team_aggregate
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="consent_grants")

    __table_args__ = (
        UniqueConstraint("user_id", "scope", name="uq_user_scope"),
    )

    def __repr__(self) -> str:
        return f"<ConsentGrant user={self.user_id} scope={self.scope} granted={self.granted} v={self.policy_version}>"
