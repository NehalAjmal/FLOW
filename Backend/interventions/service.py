# interventions/service.py
# The database side of gating: collect the real facts for one user,
# then ask the pure check_gate() function in gating.py.

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from db_models.calendar_cache import CalendarCache
from db_models.intervention import Intervention
from db_models.session import Session
from db_models.user_settings import UserSettings
from interventions.gating import GateResult, check_gate

# Only these states lead to a prompt. deep_work and neutral are status
# messages, not prompts, so they never use up the 15-minute gap.
PROMPT_STATES = {"fatigue", "stuck", "passive", "distracted"}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """MySQL hands back datetimes without a time zone. We store UTC, so say so."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_settings(db: DBSession, user_id: str) -> UserSettings:
    """Return the user's settings row, creating it with defaults the first time."""
    row = db.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id, timezone="UTC")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def in_meeting(db: DBSession, user_id: str, now: datetime) -> bool:
    """True if a cached calendar event covers this moment."""
    naive_now = now.replace(tzinfo=None)   # MySQL compares naive UTC values
    hit = (
        db.query(CalendarCache.id)
        .filter(
            CalendarCache.user_id == user_id,
            CalendarCache.starts_at <= naive_now,
            CalendarCache.ends_at > naive_now,
        )
        .first()
    )
    return hit is not None


def last_prompt_at(db: DBSession, user_id: str) -> Optional[datetime]:
    """When this user last saw a prompt, in any session."""
    latest = (
        db.query(func.max(Intervention.shown_at))
        .filter(Intervention.user_id == user_id)
        .scalar()
    )
    return _aware(latest)


def gate_for_user(db: DBSession, user_id: str, now: datetime) -> GateResult:
    s = get_settings(db, user_id)
    quiet = (s.quiet_start, s.quiet_end) if s.quiet_start and s.quiet_end else None
    return check_gate(
        now,
        paused_until=_aware(s.paused_until),
        on_break=False,                      # TODO Task 3: True while a break is running
        in_meeting=in_meeting(db, user_id, now),
        quiet_hours=quiet,
        tz_name=s.timezone,
        last_prompt_at=last_prompt_at(db, user_id),
    )


def record_intervention(
    db: DBSession,
    session: Session,
    kind: str,
    payload: dict,
    focus_score: Optional[float],
    now: datetime,
) -> Intervention:
    """Save a prompt that is about to be shown, and count it on the session."""
    row = Intervention(
        user_id=session.user_id,
        session_id=session.id,
        kind=kind,
        title=payload.get("title"),
        message=payload.get("message"),
        action_label=payload.get("action_label"),
        focus_score=focus_score,
        shown_at=now,
    )
    db.add(row)
    session.interventions_total = (session.interventions_total or 0) + 1
    db.commit()
    db.refresh(row)
    return row
