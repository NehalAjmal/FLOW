from typing import Optional, Any
from sqlalchemy.orm import Session
from db_models.audit_log import AuditLog


def log_admin_action(
    db: Session,
    actor_id: Optional[str],
    actor_email: Optional[str],
    action: str,
    target_id: Optional[str] = None,
    details: Optional[Any] = None,
) -> AuditLog:
    """
    Record an administrative action to the immutable audit log table.
    """
    entry = AuditLog(
        actor_id=actor_id,
        actor_email=actor_email,
        action=action,
        target_id=target_id,
        details=details if isinstance(details, dict) else ({"info": details} if details else None),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
