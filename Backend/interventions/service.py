# interventions/service.py
# The database side of gating: collect the real facts for one user,
# then ask the pure check_gate() function in gating.py.

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from db_models.calendar_cache import CalendarCache
from db_models.intervention import Intervention
from db_models.session import Session
from db_models.user_settings import UserSettings
from interventions.gating import GateResult, check_gate
from breaks_app.service import user_on_break

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


def latest_prompt(db: DBSession, user_id: str) -> Optional[Intervention]:
    """The last prompt this user saw, in any session (or None)."""
    return (
        db.query(Intervention)
        .filter(Intervention.user_id == user_id)
        .order_by(Intervention.shown_at.desc())
        .first()
    )


def gate_for_user(db: DBSession, user_id: str, now: datetime) -> GateResult:
    s = get_settings(db, user_id)
    quiet = (s.quiet_start, s.quiet_end) if s.quiet_start and s.quiet_end else None
    last = latest_prompt(db, user_id)
    snoozed_until = _aware(last.snooze_until) if last and last.response == "snoozed" else None
    return check_gate(
        now,
        paused_until=_aware(s.paused_until),
        on_break=user_on_break(db, user_id),
        in_meeting=in_meeting(db, user_id, now),
        quiet_hours=quiet,
        tz_name=s.timezone,
        last_prompt_at=_aware(last.shown_at) if last else None,
        snoozed_until=snoozed_until,
    )


def record_intervention(
    db: DBSession,
    session: Session,
    kind: str,
    payload: dict,
    focus_score: Optional[float],
    now: datetime,
    explanation: Optional[dict] = None,
) -> Intervention:

    """Persist a prompt and its original decision evidence."""

    row = Intervention(
        user_id=session.user_id,
        session_id=session.id,
        kind=kind,
        title=payload.get("title"),
        message=payload.get("message"),
        action_label=payload.get("action_label"),
        focus_score=focus_score,
        shown_at=now,
        explanation=explanation,
    )

    db.add(row)

    session.interventions_total = (
        session.interventions_total or 0
    ) + 1

    db.commit()
    db.refresh(row)

    return row
# ── Task 2: responses ─────────────────────────────────────

RESPONSES = {"accepted", "dismissed", "snoozed"}
OVERRIDE_REASONS = {"incident", "deploy", "pairing", "other"}
REPORT_REASONS = {"wrong_time", "in_meeting", "too_frequent", "not_needed", "other"}


class AlreadyAnswered(Exception):
    """A prompt gets one answer. Reporting it as bad is separate and always allowed."""


def get_for_user(db: DBSession, intervention_id: str, user_id: str) -> Optional[Intervention]:
    """Only return the prompt if it belongs to this user (ownership check)."""
    return (
        db.query(Intervention)
        .filter(Intervention.id == intervention_id, Intervention.user_id == user_id)
        .first()
    )


def _answer(db: DBSession, row: Intervention, response: str, now: datetime) -> None:
    if row.response is not None:
        raise AlreadyAnswered(row.response)
    row.response = response
    row.responded_at = now
    if response == "accepted":
        session = db.get(Session, row.session_id)
        if session is not None:
            session.interventions_accepted = (session.interventions_accepted or 0) + 1


def respond(db: DBSession, row: Intervention, response: str,
            snooze_minutes: Optional[int], now: datetime) -> Intervention:
    _answer(db, row, response, now)
    if response == "snoozed":
        row.snooze_until = now + timedelta(minutes=snooze_minutes or 10)
    db.commit()
    return row


def override(db: DBSession, row: Intervention, reason: str, now: datetime) -> Intervention:
    _answer(db, row, "overridden", now)
    row.override_reason = reason
    db.commit()
    return row


def report(db: DBSession, row: Intervention, reason: str, free_text: Optional[str]) -> Intervention:
    row.report_reason = reason
    row.report_text = (free_text or "").strip()[:1000] or None
    db.commit()
    return row


def session_counts(db: DBSession, session_id: str) -> dict:
    """How many prompts a session got and what happened to each one."""
    rows = db.query(Intervention).filter(Intervention.session_id == session_id).all()
    counts = {"shown": len(rows), "accepted": 0, "dismissed": 0, "snoozed": 0,
              "overridden": 0, "unanswered": 0, "reported": 0}
    for r in rows:
        counts[r.response or "unanswered"] += 1
        if r.report_reason:
            counts["reported"] += 1
    return counts
