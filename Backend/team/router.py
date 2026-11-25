# team/router.py
# GET /team/summary: the Team page every member sees (employees and admins).
# Team averages only, never a person, and nothing at all below five people
# who share with the team. Shape: contract section 7 plus the optional
# averages from "Admin: people" (focus_minutes_per_day, sessions_per_day,
# break_uptake, peak_hours, focus_minutes_this_week).

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.team import Team
from db_models.user import User
from team.metrics import TeamView, wrap

router = APIRouter()


@router.get("/summary")
def get_team_summary(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    view = TeamView(db, current_user)
    team = db.get(Team, current_user.team_id) if current_user.team_id else None
    out = wrap(view.group_size, view.team_summary)
    out["team_name"] = team.name if team else None
    return out
