# admin/people.py
# The admin's per-person pages: GET /admin/members and /admin/members/{id}.
#
# The contract (frontend/CONTRACT_NOTES.md, "Admin: people") lets the team's
# admin see each member's coarse week: time, counts and how they answer
# nudges. These functions build only those fields. There is deliberately no
# task text, window title, app, typing, camera score or pressure curve here.

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from db_models.intervention import Intervention
from db_models.session import Session
from db_models.user import User
from insights.service import _aware, _iso, _naive, marks
from team.metrics import (TeamView, focus_by_date, is_live, last_days, load_sessions,
                          local_date, session_end, strain_by_date, strain_level,
                          tick_strain, trend, utc_start)

NUDGE_WORDS = {"accepted": "taken", "snoozed": "snoozed", "dismissed": "dismissed", "overridden": "dismissed"}


def _last_active(db: DBSession, member: User, now: datetime) -> Optional[str]:
    last = (db.query(Session).filter(Session.user_id == member.id)
            .order_by(Session.start_time.desc()).first())
    if not last or not last.start_time:
        return None
    return session_end(last, now).isoformat()


def summary(view: TeamView, member: User) -> dict:
    """MemberSummary: one person, the current week (Mon..Sun in the admin's time zone)."""
    db, tz, now, monday = view.db, view.tz, view.now, view.monday
    week_from = utc_start(monday, tz)
    prev_from = utc_start(monday - timedelta(days=7), tz)

    week = load_sessions(db, [member.id], week_from, now + timedelta(seconds=1))
    prev = load_sessions(db, [member.id], prev_from, week_from)

    per_day = focus_by_date(week, tz, view.summ)
    days = [monday + timedelta(days=i) for i in range(7)]

    nudges = {"taken": 0, "snoozed": 0, "dismissed": 0}
    for p in db.query(Intervention).filter(
            Intervention.user_id == member.id, Intervention.response.isnot(None),
            Intervention.shown_at >= _naive(week_from)).all():
        nudges[NUDGE_WORDS[p.response]] += 1

    # "vs last week" only makes sense if they were on FLOW for the whole of last week.
    joined = _aware(member.created_at) if member.created_at else None
    prev_minutes = None
    if joined is None or joined <= prev_from:
        prev_minutes = sum(view.summ(s)["focus_minutes"] for s in prev)

    return {
        "id": member.id,
        "name": member.full_name,
        "focus_by_day": [per_day.get(d, 0) for d in days],
        "sessions": len(week),
        "breaks_taken": sum(view.summ(s)["breaks_taken"] for s in week),
        "breaks_suggested": sum(view.summ(s)["breaks_suggested"] for s in week),
        "nudges": nudges,
        "strain": strain_level(*tick_strain(week)),
        "last_active_at": _last_active(db, member, now),
        "in_session": any(is_live(s, now) for s in week),
        "prev_focus_minutes": prev_minutes,
    }


def list_members(view: TeamView) -> List[dict]:
    return [summary(view, m) for m in view.people]


def find(view: TeamView, member_id: str) -> Optional[User]:
    """Only someone on the admin's team who shares with the team. Anyone else is 'not found',
    so the endpoint doesn't reveal whether an id exists on another team."""
    return next((m for m in view.people if m.id == member_id), None)


def detail(view: TeamView, member: User) -> dict:
    """MemberDetail: the week as timelines, plus 30 days of focus and 14 days of strain."""
    db, tz, now, monday = view.db, view.tz, view.now, view.monday

    days_out = []
    for i in range(7):
        d = monday + timedelta(days=i)
        start = utc_start(d, tz)
        sessions = load_sessions(db, [member.id], start, start + timedelta(days=1))
        breaks, nudges = marks(db, sessions, now)
        days_out.append({
            "date": d.isoformat(),
            "sessions": [{"start": _iso(s.start_time), "end": session_end(s, now).isoformat(),
                          "demand": s.declared_difficulty or "moderate"} for s in sessions],
            "breaks": breaks,
            "nudges": nudges,
        })

    month_days = last_days(now, tz, 30)
    month = load_sessions(db, [member.id], utc_start(month_days[0], tz), now + timedelta(seconds=1))
    fortnight = month_days[-14:]
    recent = [s for s in month if local_date(s.start_time, tz) >= fortnight[0]]

    return {
        "summary": summary(view, member),
        "days": days_out,
        "focus_trend": trend(focus_by_date(month, tz, view.summ), month_days, fill_zero=True),
        "strain_trend": trend(strain_by_date(recent, tz), fortnight),
    }
