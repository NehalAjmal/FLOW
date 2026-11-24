# admin/router.py

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from db_models.base import get_db
from db_models.user import User
from auth.dependencies import require_admin
from .schemas import AdminDashboardResponse
from .service import get_admin_dashboard
from .audit import log_admin_action
from . import invites as invite_service
from . import people
from team.metrics import TeamView, wrap

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
    # Only this team's record: actions by people on the admin's team.
    team_ids = [u.id for u in db.query(User).filter(User.team_id == current_user.team_id).all()] \
        if current_user.team_id else [current_user.id]
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.actor_id.in_(team_ids))
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


# ── Team page endpoints (contract section 7 and "Admin: people") ──────────────
# Every one is admin only (require_admin answers 403 to anyone else) and only
# ever looks at the admin's own team.

CAN_SEE = [
    "Team averages and trends",
    "Each person's focus time, sessions and breaks",
    "How each person answers break suggestions",
]
CANNOT_SEE = [
    "What anyone is working on (task text)",
    "Window titles, apps or websites",
    "Typing, mouse or camera data",
]


@router.get("/privacy-status")
def privacy_status(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    view = TeamView(db, current_user)
    return {"group_size": view.group_size, "suppressed": view.group_size < 5,
            "can_see": CAN_SEE, "cannot_see": CANNOT_SEE}


@router.get("/members")
def list_members(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    return {"items": people.list_members(TeamView(db, current_user))}


@router.get("/members/{member_id}")
def member_detail(member_id: str, current_user: User = Depends(require_admin),
                  db: DBSession = Depends(get_db)):
    view = TeamView(db, current_user)
    member = people.find(view, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="That person is not on your team.")
    # Every look at a person goes on the record; the team can ask to see it.
    log_admin_action(db=db, actor_id=current_user.id, actor_email=current_user.email,
                     action="member.view", target_id=member.id)
    return people.detail(view, member)


@router.get("/summary")
def admin_summary(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    view = TeamView(db, current_user)
    return wrap(view.group_size, view.admin_summary)


@router.get("/trend")
def admin_trend(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    view = TeamView(db, current_user)
    return wrap(view.group_size, view.admin_trend)


@router.get("/insights")
def admin_insights(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    view = TeamView(db, current_user)
    return wrap(view.group_size, view.admin_insights)


@router.get("/strain")
def admin_strain(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    view = TeamView(db, current_user)
    return wrap(view.group_size, view.admin_strain)


@router.get("/meeting-window")
def admin_meeting_window(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    view = TeamView(db, current_user)
    return wrap(view.group_size, view.admin_meeting_window)


class InviteIn(BaseModel):
    valid_for_hours: int = Field(invite_service.DEFAULT_HOURS, ge=1, le=invite_service.MAX_HOURS)


def _need_team(user: User):
    if not user.team_id:
        raise HTTPException(status_code=404, detail="Team not found")


@router.post("/invites", status_code=201)
def create_invite(body: InviteIn, current_user: User = Depends(require_admin),
                  db: DBSession = Depends(get_db)):
    _need_team(current_user)
    inv, url = invite_service.create(db, current_user, body.valid_for_hours)
    log_admin_action(db=db, actor_id=current_user.id, actor_email=current_user.email,
                     action="invite.create", target_id=inv.id,
                     details={"valid_for_hours": body.valid_for_hours})
    return invite_service.to_json(inv, url)


@router.get("/invites")
def list_invites(current_user: User = Depends(require_admin), db: DBSession = Depends(get_db)):
    _need_team(current_user)
    return {"items": [invite_service.to_json(i) for i in invite_service.list_for_team(db, current_user.team_id)]}


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: str, current_user: User = Depends(require_admin),
                  db: DBSession = Depends(get_db)):
    if not invite_service.revoke(db, current_user, invite_id):
        raise HTTPException(status_code=404, detail="Invite not found")
    log_admin_action(db=db, actor_id=current_user.id, actor_email=current_user.email,
                     action="invite.revoke", target_id=invite_id)
    return Response(status_code=204)
