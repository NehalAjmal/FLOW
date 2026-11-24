# admin/router.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from db_models.base import get_db
from db_models.user import User
from auth.dependencies import require_admin
from .schemas import AdminDashboardResponse
from .service import get_admin_dashboard
from .audit import log_admin_action

router = APIRouter()


@router.get("/dashboard", response_model=AdminDashboardResponse)
def admin_dashboard(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """
    Full admin dashboard payload. Requires admin JWT.
    Returns team aggregate data — no individual session details.
    """
    log_admin_action(
        db=db,
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="admin.dashboard_view",
        target_id=current_user.team_id,
    )

    if not current_user.team_id:
        # Admin has no team (solo account) — dashboard handles it with real zeros
        return get_admin_dashboard(db=db, team_id=None)

    return get_admin_dashboard(db=db, team_id=current_user.team_id)


@router.post("/send-break-alert")
def send_break_alert(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """
    Notify all active employees to take a break.
    In production this would push a notification via WebSocket.
    For demo: returns success immediately with the real recipient count.
    """
    notified = 0
    if current_user.team_id:
        from db_models.user import User as Usermodel
        notified = db.query(Usermodel).filter(
            Usermodel.team_id == current_user.team_id,
            Usermodel.role == "employee",
        ).count()

    log_admin_action(
        db=db,
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="admin.send_break_alert",
        target_id=current_user.team_id,
        details={"notified_count": notified},
    )

    return {
        "status": "ok",
        "message": "Break alert sent to all active employees.",
        "notified_count": notified,
    }


@router.post("/invite-employee")
def invite_employee(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """
    Returns the company code for the admin to share with employees.
    """
    from db_models.team import Team
    team = db.query(Team).filter(Team.id == current_user.team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    log_admin_action(
        db=db,
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="admin.invite_employee",
        target_id=team.id,
        details={"company_code": team.company_code},
    )

    return {
        "company_code": team.company_code,
        "message": f"Share code '{team.company_code}' with employees during registration.",
    }


@router.get("/audit-log")
def get_audit_log(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
    limit: int = 50,
):
    """
    Returns audit trail of administrative actions per CONTRACT_NOTES.md §7.
    """
    from db_models.audit_log import AuditLog
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    items = []
    for l in logs:
        items.append({
            "id": l.id,
            "action": l.action,
            "at": l.timestamp.isoformat() if l.timestamp else None,
            "actor": l.actor_email or l.actor_id or "system",
            "target_id": l.target_id,
            "details": l.details,
        })
    return {"items": items}
