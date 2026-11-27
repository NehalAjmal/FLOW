# history/service.py
# Turns stored sessions into the summaries and replay timeline the app shows.

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from breaks_app.service import BREAK_PROMPT_KINDS
from db_models.breaks import Break
from db_models.intervention import Intervention
from db_models.session import Session

PAGE_SIZE = 20


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt):
    return _aware(dt).isoformat() if dt else None


def _minutes_between(a: datetime, b: datetime) -> float:
    return (_aware(b) - _aware(a)).total_seconds() / 60


def session_summary(db: DBSession, s: Session, until: Optional[datetime] = None) -> dict:
    """One row of history. focus_minutes = time in the session minus time on breaks.
    An unfinished session counts up to `until` (default: now)."""
    breaks = db.query(Break).filter(Break.session_id == s.id).all()
    end = s.end_time or until or datetime.now(timezone.utc)
    total = _minutes_between(s.start_time, end) if s.start_time else 0
    on_break = sum(
        _minutes_between(b.taken_at, b.ended_at or end) for b in breaks if b.taken_at
    )
    suggested = (
        db.query(Intervention)
        .filter(Intervention.session_id == s.id, Intervention.kind.in_(BREAK_PROMPT_KINDS))
        .count()
    )
    return {
        "session_id": s.id,
        "started_at": _iso(s.start_time),
        "ended_at": _iso(s.end_time),
        "focus_minutes": max(0, round(total - on_break)),
        "planned_minutes": s.planned_duration_min,
        "demand": s.declared_difficulty,
        "task_text": s.task_description,
        "breaks_suggested": suggested,
        "breaks_taken": sum(1 for b in breaks if b.taken),
    }


def list_sessions(db: DBSession, user_id: str, page: int,
                  start: Optional[datetime], end: Optional[datetime]) -> dict:
    q = db.query(Session).filter(Session.user_id == user_id)
    if start:
        q = q.filter(Session.start_time >= start.replace(tzinfo=None))
    if end:
        q = q.filter(Session.start_time < end.replace(tzinfo=None))
    rows = (
        q.order_by(Session.start_time.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE + 1)                 # one extra row tells us if there's another page
        .all()
    )
    return {
        "items": [session_summary(db, s) for s in rows[:PAGE_SIZE]],
        "page": page,
        "has_more": len(rows) > PAGE_SIZE,
    }


def _tick_minute(entry: dict, index: int, start: datetime) -> float:
    """Minute into the session for a signal_log entry: server time if we have it,
    otherwise its position (one tick = 30 s)."""
    at = entry.get("at")
    if at:
        return _minutes_between(start, datetime.fromisoformat(at))
    return index * 0.5


STATE_WORDS = {
    "deep_work": "deep work", "neutral": "steady", "distracted": "distracted",
    "fatigue": "tired", "stuck": "stuck", "passive": "off task", "unknown": "unknown",
}


def replay(db: DBSession, s: Session) -> dict:
    start = _aware(s.start_time)
    events: List[dict] = []

    def add(when: datetime, kind: str, text: str):
        events.append({"minute": round(max(0.0, _minutes_between(start, when)), 1), "kind": kind, "text": text})

    events.append({"minute": 0.0, "kind": "start",
                   "text": f"Started {s.task_description or 'a session'}"
                           + (f" ({s.declared_difficulty}, {s.planned_duration_min} min planned)"
                              if s.declared_difficulty and s.planned_duration_min else "")})

    previous = None
    for i, entry in enumerate(s.signal_log or []):
        state = entry.get("state")
        if state and state != previous and previous is not None:
            events.append({"minute": round(_tick_minute(entry, i, start), 1), "kind": "state",
                           "text": f"{STATE_WORDS.get(previous, previous)} → {STATE_WORDS.get(state, state)}"})
        previous = state or previous

    for p in db.query(Intervention).filter(Intervention.session_id == s.id).all():
        answer = {"accepted": "you took it", "dismissed": "you dismissed it",
                  "snoozed": "you snoozed it", "overridden": f"you overrode it ({p.override_reason})"}
        add(p.shown_at, "nudge", f"{p.title or 'Prompt'}: {answer.get(p.response, 'no answer')}")

    for b in db.query(Break).filter(Break.session_id == s.id).all():
        if b.taken_at:
            add(b.taken_at, "break", "Break started")
        if b.ended_at:
            text = f"Back after {b.duration_actual_min} min"
            if b.resumption_lag_sec is not None:
                text += f", typing again {round(b.resumption_lag_sec)} s later"
            add(b.ended_at, "break_end", text)

    if s.end_time:
        add(s.end_time, "end", "Session ended")

    events.sort(key=lambda e: e["minute"])
    return {"events": events, "what_flow_learned": learned_lines(s.learned_updates)}


def learned_lines(learned: Optional[dict]) -> List[str]:
    """Plain sentences from what the learner stored at session end. Nothing is invented:
    the learner returns 90 min / minute 45 as placeholders until it has data,
    so a line only appears once the number is really learned."""
    if not learned:
        return []
    lines = []
    n = learned.get("sessions_in_model") or 0
    if learned.get("ultradian_cycle_minutes") and n >= 3:        # learner needs 3 sessions for the cycle
        lines.append(f"Your focus cycle estimate is now {learned['ultradian_cycle_minutes']} min (from {n} sessions).")
    t = learned.get("trough_samples") or 0
    if learned.get("trough_minute") and t >= 1:
        lines.append(f"Your focus usually dips around minute {learned['trough_minute']} "
                     f"(from {t} session{'s' if t != 1 else ''}).")
    return lines
