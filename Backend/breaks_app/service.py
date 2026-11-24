# breaks_app/service.py
# Task 3: break tracking, the study's main measure.
#   start / end a break
#   restoration estimate: was behaviour more on-task after the break than before?
#   resumption lag: how long until the user typed again after the break
#   focus ratings: 1-5 self-reports

from datetime import datetime, timezone
from statistics import mean
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from db_models.breaks import Break
from db_models.intervention import Intervention
from db_models.rating import Rating
from db_models.session import Session
from engine.deviation import DeviationEngine

WINDOW_TICKS = 6          # 6 ticks x 30 s = 3 minutes before and after a break
BREAK_PROMPT_KINDS = {"trough", "fatigue"}   # prompts whose action is "take a break"


class BreakError(Exception):
    pass


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tick_time(entry: dict) -> Optional[datetime]:
    """Server receive time of a signal_log entry ('at'). Older entries don't have it."""
    at = entry.get("at")
    return _aware(datetime.fromisoformat(at)) if at else None


def active_break(db: DBSession, session_id: str) -> Optional[Break]:
    return (
        db.query(Break)
        .filter(Break.session_id == session_id, Break.taken.is_(True), Break.ended_at.is_(None))
        .first()
    )


def user_on_break(db: DBSession, user_id: str) -> bool:
    hit = (
        db.query(Break.id)
        .join(Session, Session.id == Break.session_id)
        .filter(Session.user_id == user_id, Break.taken.is_(True), Break.ended_at.is_(None))
        .first()
    )
    return hit is not None


# ── windows of behaviour around a break ──────────────────

def ticks_before(log: List[dict], moment: datetime) -> List[dict]:
    return [e for e in log if _tick_time(e) and _tick_time(e) < moment][-WINDOW_TICKS:]


def ticks_after(log: List[dict], moment: datetime) -> List[dict]:
    return [e for e in log if _tick_time(e) and _tick_time(e) >= moment][:WINDOW_TICKS]


def window_deviation(ticks: List[dict], difficulty: str) -> float:
    """Mridul's deviation score averaged over a window (0 = on task, 1 = off task)."""
    engine = DeviationEngine()
    score = 0.0
    for e in ticks:
        score = engine.compute(
            keystrokes=e.get("keystrokes", 0),
            switches=e.get("switches", 0),
            idle_seconds=e.get("idle", 0),
            declared_difficulty=difficulty,
        )
    return score   # the engine returns the running mean of everything it has seen


def restoration_from(dev_before: float, dev_after: float) -> float:
    """0.5 = no change, above 0.5 = more on-task after the break, below = less."""
    return round(min(1.0, max(0.0, 0.5 + (dev_before - dev_after) / 2)), 3)


# ── start / end ───────────────────────────────────────────

def start_break(db: DBSession, session: Session, intervention_id: Optional[str], now: datetime) -> Break:
    if session.end_time is not None:
        raise BreakError("session has ended")
    if active_break(db, session.id):
        raise BreakError("a break is already running")

    suggested_at = None
    if intervention_id:
        prompt = db.get(Intervention, intervention_id)
        if prompt is None or prompt.session_id != session.id:
            raise BreakError("intervention does not belong to this session")
        suggested_at = prompt.shown_at

    before = ticks_before(session.signal_log or [], now)
    row = Break(
        session_id=session.id,
        intervention_id=intervention_id,
        suggested_at=suggested_at,
        taken=True,
        taken_at=now,
        keystrokes_before=mean(e.get("keystrokes", 0) for e in before) if before else None,
        switches_before=mean(e.get("switches", 0) for e in before) if before else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def end_break(db: DBSession, row: Break, actual_minutes: Optional[int], now: datetime) -> Break:
    if row.ended_at is not None:
        raise BreakError("break already ended")
    row.ended_at = now
    if actual_minutes is not None:
        row.duration_actual_min = actual_minutes
    else:
        row.duration_actual_min = round((now - _aware(row.taken_at)).total_seconds() / 60)
    db.commit()
    return row


# ── filled in later, once the user is back at work ───────

def update_pending(db: DBSession, session: Session) -> None:
    """Called on every agent tick. Fills in restoration and resumption lag
    for ended breaks once enough post-break ticks exist. Does not commit."""
    log = session.signal_log or []
    pending = (
        db.query(Break)
        .filter(Break.session_id == session.id, Break.ended_at.isnot(None),
                (Break.restoration_score.is_(None)) | (Break.resumption_lag_sec.is_(None)))
        .all()
    )
    for b in pending:
        ended = _aware(b.ended_at)
        after = ticks_after(log, ended)

        if b.resumption_lag_sec is None:
            first_typing = next((e for e in after if e.get("keystrokes", 0) > 0), None)
            if first_typing is not None:
                # 30-second ticks, so this is accurate to about 30 s
                b.resumption_lag_sec = max(0.0, (_tick_time(first_typing) - ended).total_seconds())
                b.resumption_source = "log"

        if b.restoration_score is None and len(after) >= WINDOW_TICKS:
            before = ticks_before(log, _aware(b.taken_at))
            if before:
                difficulty = session.declared_difficulty or "moderate"
                b.restoration_score = restoration_from(
                    window_deviation(before, difficulty), window_deviation(after, difficulty)
                )
                b.keystrokes_after = mean(e.get("keystrokes", 0) for e in after)
                b.switches_after = mean(e.get("switches", 0) for e in after)


def record_resumption(db: DBSession, row: Break, seconds: float) -> Break:
    """The local agent measured it exactly (first keystroke after the break). Wins over the log estimate."""
    row.resumption_lag_sec = seconds
    row.resumption_source = "agent"
    db.commit()
    return row


def add_rating(db: DBSession, user_id: str, session_id: str, kind: str, value: int,
               context_id: Optional[str], now: datetime) -> Rating:
    row = Rating(user_id=user_id, session_id=session_id, kind=kind, value=value,
                 context_id=context_id, created_at=now)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def summary(db: DBSession, session_id: str) -> dict:
    breaks = db.query(Break).filter(Break.session_id == session_id).order_by(Break.taken_at).all()
    suggested = (
        db.query(Intervention)
        .filter(Intervention.session_id == session_id, Intervention.kind.in_(BREAK_PROMPT_KINDS))
        .count()
    )

    def iso(dt):
        return _aware(dt).isoformat() if dt else None

    return {
        "suggested": suggested,
        "taken": sum(1 for b in breaks if b.taken),
        "breaks": [
            {
                "break_id": b.id,
                "started_at": iso(b.taken_at),
                "ended_at": iso(b.ended_at),
                "intervention_id": b.intervention_id,
                "actual_minutes": b.duration_actual_min,
                "restoration_score": b.restoration_score,
                "resumption_lag_sec": b.resumption_lag_sec,
                "resumption_source": b.resumption_source,
            }
            for b in breaks
        ],
    }
