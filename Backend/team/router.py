from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from db_models.base import get_db
from db_models.user import User
from db_models.team import Team
from db_models.session import Session
from consent.service import has_consent
from .schemas import TeamSummaryResponse, TeamMetrics, EmployeeStatus
from auth.dependencies import require_admin

router = APIRouter()

MIN_TEAM_SIZE_THRESHOLD = 5


@router.get("/summary", response_model=TeamSummaryResponse)
def get_team_summary(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    team_id = current_user.team_id
    team = db.query(Team).filter(Team.id == team_id).first() if team_id else None
    team_name = team.name if team else (f"Team {team_id}" if team_id else "No Team")

    # 1. Fetch all users in this team who granted 'team_aggregate' consent
    all_members = db.query(User).filter(User.team_id == team_id).all() if team_id else []
    eligible_members = [m for m in all_members if has_consent(db, m.id, "team_aggregate")]
    group_size = len(eligible_members)

    # 2. PRIVACY SUPPRESSION: Withheld below 5 members (CONTRACT_NOTES.md §7)
    if group_size < MIN_TEAM_SIZE_THRESHOLD:
        return TeamSummaryResponse(
            group_size=group_size,
            suppressed=True,
            reason="Team metrics withheld: at least 5 consenting members required for privacy protection",
            metrics=None,
            team_name=team_name,
            average_focus_score=0,
            active_sessions_count=0,
            total_employees=group_size,
            employees=[],
        )

    # 3. REAL AGGREGATES FOR TEAMS WITH 5+ MEMBERS
    employees_data = []
    total_score = 0
    active_count = 0

    for i, member in enumerate(eligible_members):
        # Strict privacy: anonymous display name, never personal names
        display_name = f"Member {i+1}"

        last_session = (
            db.query(Session)
            .filter(Session.user_id == member.id)
            .order_by(Session.start_time.desc())
            .first()
        )

        status = "Offline"
        score = 75
        risk = "Low"

        if last_session:
            score = last_session.focus_score or 75
            if last_session.end_time is None:
                status = "In Flow"
                active_count += 1

            if score < 50:
                risk = "High"
            elif score < 70:
                risk = "Medium"

        total_score += score
        employees_data.append(EmployeeStatus(
            id=f"member-{i+1}",
            display_name=display_name,
            current_status=status,
            focus_score=score,
            burnout_risk=risk,
        ))

    avg_score = int(total_score / group_size) if group_size > 0 else 0

    metrics = TeamMetrics(
        average_focus=avg_score,
        trend=[],
        active_sessions_count=active_count,
        total_employees=group_size,
    )

    return TeamSummaryResponse(
        group_size=group_size,
        suppressed=False,
        metrics=metrics,
        team_name=team_name,
        average_focus_score=avg_score,
        active_sessions_count=active_count,
        total_employees=group_size,
        employees=employees_data,
    )
