# admin/service.py
# Business logic for the admin dashboard.
# Aggregates team data without exposing any individual's personal session details.
# Privacy rule: admins see counts and averages, never individual signal logs.

from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session as DBSession

from db_models.user import User
from db_models.session import Session
from db_models.team import Team
from consent.service import has_consent
from .schemas import AdminDashboardResponse, BurnoutFlag, TrendPoint
from team import metrics

MIN_ADMIN_TEAM_THRESHOLD = 5


def _empty_dashboard(group_size: int = 0, suppressed: bool = False, reason: Optional[str] = None, company_code: Optional[str] = None) -> AdminDashboardResponse:
    return AdminDashboardResponse(
        group_size=group_size,
        suppressed=suppressed,
        reason=reason,
        total_employees=group_size,
        active_right_now=0,
        avg_focus_score=0,
        burnout_flags_count=0,
        best_meeting_window="--:--",
        trend_7_days=[],
        burnout_flags=[],
        state_distribution={},
        company_code=company_code,
    )


def get_admin_dashboard(db: DBSession, team_id: Optional[str], tz=None) -> AdminDashboardResponse:
    """
    Build the full admin dashboard payload for a team.
    Enforces privacy threshold: metrics withheld below 5 members.
    Zero named burnout flags.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    week_ago = now - timedelta(days=7)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    if not team_id:
        return _empty_dashboard()

    team = db.query(Team).filter(Team.id == team_id).first()
    company_code = team.company_code if team else None

    # Fetch all employees in this team
    all_employees = db.query(User).filter(
        User.team_id == team_id,
        User.role == "employee"
    ).all()

    # Filter by 'team_aggregate' consent grant per CONTRACT_NOTES.md §223
    eligible_employees = [e for e in all_employees if has_consent(db, e.id, "team_aggregate")]
    group_size = len(eligible_employees)

    if group_size == 0:
        return _empty_dashboard(company_code=company_code)

    # 5-MEMBER PRIVACY SUPPRESSION
    if group_size < MIN_ADMIN_TEAM_THRESHOLD:
        return _empty_dashboard(
            group_size=group_size,
            suppressed=True,
            reason="Admin aggregate metrics withheld: at least 5 consenting members required for privacy protection",
            company_code=company_code,
        )

    employee_ids = [e.id for e in eligible_employees]

    # Sessions this week
    week_sessions = db.query(Session).filter(
        Session.user_id.in_(employee_ids),
        Session.start_time >= week_ago
    ).all()

    # Today's sessions (active right now = no end_time)
    active_now = db.query(Session).filter(
        Session.user_id.in_(employee_ids),
        Session.start_time >= today_start,
        Session.end_time == None
    ).count()

    # Average focus score across all week sessions
    scores = [s.focus_score for s in week_sessions if s.focus_score is not None]
    avg_score = int(sum(scores) / len(scores)) if scores else 0

    # Yesterday's focus score for delta
    yesterday_sessions = [
        s for s in week_sessions
        if s.start_time and yesterday_start <= s.start_time.replace(tzinfo=None) < today_start and s.focus_score
    ]
    yesterday_scores = [s.focus_score for s in yesterday_sessions]
    yesterday_avg = int(sum(yesterday_scores) / len(yesterday_scores)) if yesterday_scores else avg_score
    avg_focus_delta = avg_score - yesterday_avg

    # Today's sessions count
    today_sessions = [
        s for s in week_sessions
        if s.start_time and s.start_time.replace(tzinfo=None) >= today_start
    ]
    sessions_today_count = len(today_sessions)

    # Average duration
    durations = [s.actual_duration_min for s in week_sessions if s.actual_duration_min]
    avg_duration = int(sum(durations) / len(durations)) if durations else 0

    # Burnout flags — STRICT PRIVACY: ZERO NAMED FLAGS!
    burnout_flags = []
    for idx, emp in enumerate(eligible_employees):
        emp_sessions = [s for s in week_sessions if s.user_id == emp.id]
        emp_scores = [s.focus_score for s in emp_sessions if s.focus_score]
        emp_avg = int(sum(emp_scores) / len(emp_scores)) if emp_scores else 0

        risk = None
        # Only flag based on actual low focus scores, not because employee has few sessions
        if len(emp_sessions) >= 2 and emp_avg < 40:
            risk = "high"
        elif len(emp_sessions) >= 2 and emp_avg < 55:
            risk = "medium"

        if risk:
            burnout_flags.append(BurnoutFlag(
                employee_id=f"anon-{idx+1}",
                display_name=f"Team Member #{idx+1}",  # NO real names or initials
                risk_level=risk,
                sessions_this_week=len(emp_sessions),
                avg_focus_score=emp_avg,
            ))

    # 7-day trend
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    trend = []
    for i in range(7):
        day_start = today_start - timedelta(days=6 - i)
        day_end = day_start + timedelta(days=1)
        day_sessions = [
            s for s in week_sessions
            if s.start_time and day_start <= s.start_time.replace(tzinfo=None) < day_end and s.focus_score
        ]
        day_scores = [s.focus_score for s in day_sessions]
        day_avg = int(sum(day_scores) / len(day_scores)) if day_scores else 0
        trend.append(TrendPoint(
            day=days[(day_start.weekday())],
            avg_score=day_avg
        ))

    # What the live sessions are in right now, from each one's latest tick.
    # (It used to call everyone not in a session "passive", which was invented.)
    now_aware = now.replace(tzinfo=timezone.utc)
    state_distribution = {}
    for s in db.query(Session).filter(Session.user_id.in_(employee_ids), Session.end_time == None).all():
        if not metrics.is_live(s, now_aware) or not s.signal_log:
            continue
        state = s.signal_log[-1].get("state")
        if state:
            state_distribution[state] = state_distribution.get(state, 0) + 1

    # Quietest weekday hour for the team over 14 days; "--:--" until there's enough data.
    zone = tz or timezone.utc
    window = metrics.meeting_window(
        metrics.load_sessions(db, employee_ids, now_aware - timedelta(days=14), now_aware + timedelta(seconds=1)),
        zone, now_aware)
    best_window = f"{window['start']} - {window['end']}" if window else "--:--"

    return AdminDashboardResponse(
        group_size=group_size,
        suppressed=False,
        reason=None,
        total_employees=group_size,
        active_right_now=active_now,
        avg_focus_score=avg_score,
        avg_focus_delta=avg_focus_delta,
        sessions_today=sessions_today_count,
        avg_duration_min=avg_duration,
        company_code=company_code,
        burnout_flags_count=len(burnout_flags),
        best_meeting_window=best_window,
        trend_7_days=trend,
        burnout_flags=burnout_flags,
        state_distribution=state_distribution,
    )
