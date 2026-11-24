# insights/service.py
# Everything the Insights screens show, computed only from what's stored.
# Rule for this file: if we don't have enough data for a number, return null
# (or an empty list) and say how many more sessions are needed. Never a default
# that looks like a measurement.

from datetime import date, datetime, time, timedelta, timezone
from statistics import mean, median, quantiles
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DBSession

from breaks_app.service import BREAK_PROMPT_KINDS
from db_models.breaks import Break
from db_models.calendar_cache import CalendarCache
from db_models.intervention import Intervention
from db_models.schedule import Schedule
from db_models.session import Session
from db_models.user import User
from history.service import session_summary
from interventions.service import get_settings

SESSIONS_NEEDED = 5          # finished sessions before FLOW shows learned patterns
USUAL_DAYS_NEEDED = 5        # past days with data before the "usual day" band appears
BUCKET_MIN = 5               # day view samples every 5 minutes
NUDGE_LINE_SCORE = 50.0      # focus score below which states become distracted/fatigue (prompting states)
FORECAST_HOURS = 3


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt):
    return _aware(dt).isoformat() if dt else None


def confidence(n: int) -> str:
    return "low" if n < 5 else "medium" if n < 15 else "high"


def learned(value, n: int) -> Optional[dict]:
    """The {value, sample_size, confidence} wrapper the app expects (contract section 5)."""
    if value is None or n == 0:
        return None
    return {"value": value, "sample_size": n, "confidence": confidence(n)}


def user_tz(db: DBSession, user_id: str) -> ZoneInfo:
    try:
        return ZoneInfo(get_settings(db, user_id).timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def day_bounds(d: date, tz: ZoneInfo):
    """Start and end of a local calendar day, in UTC (naive, as MySQL stores it)."""
    start = datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def sessions_between(db, user_id, start, end) -> List[Session]:
    return (
        db.query(Session)
        .filter(Session.user_id == user_id,
                Session.start_time >= _naive(start), Session.start_time < _naive(end))
        .order_by(Session.start_time)
        .all()
    )


def completed_count(db, user_id) -> int:
    return db.query(Session).filter(Session.user_id == user_id, Session.end_time.isnot(None)).count()


def _params(user: User) -> dict:
    return ((user.pattern_model or {}).get("parameters") or {}) if user else {}


def learned_cycle(user: User) -> Optional[dict]:
    """The learner returns 90 until it has 3 sessions, so only trust it from 3 on."""
    p = _params(user)
    n = len(p.get("_session_lengths") or [])
    return learned(p.get("ultradian_cycle_minutes"), n) if n >= 3 else None


# ── patterns ─────────────────────────────────────────────

def patterns(db: DBSession, user: User) -> dict:
    done = completed_count(db, user.id)
    out = {"sessions_completed": done, "sessions_needed": max(0, SESSIONS_NEEDED - done)}
    if out["sessions_needed"] > 0:
        return out                         # the app shows "still learning (n of 5)"

    p = _params(user)
    profile = p.get("fatigue_focus_profile") or {}
    if profile:
        top = sorted(profile.items(), key=lambda kv: kv[1], reverse=True)[:2]
        out["peak_hours"] = learned(sorted(int(h) for h, _ in top), done)
    out["personal_period_min"] = learned_cycle(user)

    scores = [
        b.restoration_score for b in
        db.query(Break).join(Session, Session.id == Break.session_id)
        .filter(Session.user_id == user.id, Break.restoration_score.isnot(None)).all()
    ]
    out["break_effectiveness"] = learned(round(mean(scores), 2), len(scores)) if scores else None
    return out


# ── forecast ─────────────────────────────────────────────

def forecast(db: DBSession, user: User, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    done = completed_count(db, user.id)
    cycle = learned_cycle(user)
    if done < SESSIONS_NEEDED or cycle is None:
        return {"available": False, "sessions_needed": max(0, SESSIONS_NEEDED - done),
                "windows": [], "confidence": "low", "basis": ""}

    horizon = now + timedelta(hours=FORECAST_HOURS)
    meetings = (
        db.query(CalendarCache)
        .filter(CalendarCache.user_id == user.id,
                CalendarCache.ends_at > _naive(now), CalendarCache.starts_at < _naive(horizon))
        .order_by(CalendarCache.starts_at).all()
    )
    break_len = timedelta(seconds=get_settings(db, user.id).break_length_sec or 300)

    # Where in the cycle are we? From the last break (or session start) if a session is running.
    active = (db.query(Session).filter(Session.user_id == user.id, Session.end_time.is_(None))
              .order_by(Session.start_time.desc()).first())
    cycle_start = now
    if active:
        last_break = (db.query(Break).filter(Break.session_id == active.id, Break.ended_at.isnot(None))
                      .order_by(Break.ended_at.desc()).first())
        cycle_start = _aware(last_break.ended_at) if last_break else _aware(active.start_time)

    windows = [{"start": _iso(m.starts_at), "end": _iso(m.ends_at), "kind": "meeting", "note": m.title}
               for m in meetings]
    t, cycle_len = now, timedelta(minutes=cycle["value"])
    break_at = cycle_start + cycle_len
    while t < horizon:
        if break_at <= t:
            break_at = t + cycle_len
        nxt = next((_aware(m.starts_at) for m in meetings if _aware(m.starts_at) > t), None)
        focus_end = min(break_at, horizon, nxt or horizon)
        if focus_end > t:
            windows.append({"start": _iso(t), "end": _iso(focus_end), "kind": "focus", "note": None})
        if focus_end == break_at:
            windows.append({"start": _iso(break_at), "end": _iso(break_at + break_len), "kind": "break", "note": None})
            t = break_at + break_len
            break_at = t + cycle_len
        elif nxt and focus_end == nxt:
            meeting = next(m for m in meetings if _aware(m.starts_at) == nxt)
            t = _aware(meeting.ends_at)
            break_at = t + cycle_len          # a meeting resets the cycle
        else:
            break
    windows.sort(key=lambda w: w["start"])
    basis = f"Your {cycle['value']}-min focus cycle, learned from {cycle['sample_size']} sessions"
    if meetings:
        basis += ", and your calendar"
    return {"available": True, "sessions_needed": 0, "windows": windows,
            "confidence": cycle["confidence"], "basis": basis}


# ── dashboard ────────────────────────────────────────────

def current_state(db: DBSession, user: User, now: datetime) -> Optional[str]:
    active = (db.query(Session).filter(Session.user_id == user.id, Session.end_time.is_(None))
              .order_by(Session.start_time.desc()).first())
    if active is None:
        return None
    paused_until = _aware(get_settings(db, user.id).paused_until)
    if paused_until and paused_until > now:
        return "paused"
    last_break = (db.query(Break).filter(Break.session_id == active.id, Break.ended_at.isnot(None))
                  .order_by(Break.ended_at.desc()).first())
    since = _aware(last_break.ended_at) if last_break else _aware(active.start_time)
    cycle = (learned_cycle(user) or {}).get("value") or 90     # same default the session engine uses
    pressure = (now - since).total_seconds() / 60 / cycle
    return "break_due" if pressure >= 1 else "approaching_break" if pressure >= 0.85 else "steady"


def dashboard(db: DBSession, user: User, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tz = user_tz(db, user.id)
    start, end = day_bounds(now.astimezone(tz).date(), tz)
    today = [session_summary(db, s) for s in sessions_between(db, user.id, start, end)]
    last = (db.query(Session).filter(Session.user_id == user.id)
            .order_by(Session.start_time.desc()).first())
    return {
        "today": {
            "sessions": len(today),
            "focus_minutes": sum(s["focus_minutes"] for s in today),
            "breaks_taken": sum(s["breaks_taken"] for s in today),
        },
        "current_state": current_state(db, user, now),
        "quick_start": (
            {"demand": last.declared_difficulty or "moderate",
             "minutes": last.planned_duration_min, "task_text": last.task_description}
            if last else None
        ),
        "forecast": forecast(db, user, now),
    }


# ── day view ─────────────────────────────────────────────

def _pressure_by_bucket(sessions: List[Session], day_start: datetime) -> Dict[int, float]:
    """5-minute buckets (index from local midnight) -> pressure. 1.0 = the nudge line."""
    buckets: Dict[int, List[float]] = {}
    for s in sessions:
        for e in s.signal_log or []:
            if not e.get("at") or e.get("score") is None:
                continue                                   # older ticks have no server time
            t = _aware(datetime.fromisoformat(e["at"]))
            idx = int((t - day_start).total_seconds() // (BUCKET_MIN * 60))
            if 0 <= idx < 24 * 60 // BUCKET_MIN:
                buckets.setdefault(idx, []).append((100 - float(e["score"])) / (100 - NUDGE_LINE_SCORE))
    return {i: round(mean(v), 3) for i, v in buckets.items()}


def marks(db: DBSession, sessions: List[Session], now: datetime):
    """Break marks (taken | suggested | snoozed) and nudge outcomes for these sessions.
    Used by the day view and by the admin's per-person page."""
    sids = [s.id for s in sessions]
    prompts = (db.query(Intervention).filter(Intervention.session_id.in_(sids)).all() if sids else [])
    breaks = (db.query(Break).filter(Break.session_id.in_(sids)).all() if sids else [])
    taken_from = {b.intervention_id for b in breaks if b.intervention_id}

    break_marks = [{"at": _iso(b.taken_at), "mark": "taken"} for b in breaks if b.taken_at]
    for p in prompts:
        if p.kind in BREAK_PROMPT_KINDS and p.id not in taken_from:
            break_marks.append({"at": _iso(p.shown_at),
                                "mark": "snoozed" if p.response == "snoozed" else "suggested"})

    outcome = {"accepted": "taken", "snoozed": "snoozed", "dismissed": "dismissed", "overridden": "dismissed"}
    nudges = []
    for p in prompts:
        if p.response:
            o = outcome[p.response]
        else:
            fresh = now - _aware(p.shown_at) < timedelta(minutes=5)
            o = "pending" if fresh else "ignored"
        nudges.append({"at": _iso(p.shown_at), "outcome": o})
    return sorted(break_marks, key=lambda x: x["at"]), sorted(nudges, key=lambda x: x["at"])


def day(db: DBSession, user: User, d: date, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tz = user_tz(db, user.id)
    day_start, day_end = day_bounds(d, tz)
    sessions = sessions_between(db, user.id, day_start, day_end)
    summaries = [session_summary(db, s) for s in sessions]

    timeline = []
    for s in sessions:
        end = s.end_time or (_aware(s.start_time) + timedelta(minutes=s.planned_duration_min or 0))
        timeline.append({"session_id": s.id, "start": _iso(s.start_time), "end": _iso(end),
                         "demand": s.declared_difficulty or "moderate",
                         "state": "done" if s.end_time else "active", "task_text": s.task_description})

    weekday = d.isoweekday()                               # 1 = Monday, like the schedules
    for sch in db.query(Schedule).filter(Schedule.user_id == user.id, Schedule.enabled.is_(True)).all():
        if weekday not in (sch.weekdays or []):
            continue
        s_start = datetime.combine(d, time.fromisoformat(sch.start), tzinfo=tz)
        if s_start <= now:
            continue                                       # past occurrences either happened or didn't
        s_end = datetime.combine(d, time.fromisoformat(sch.end), tzinfo=tz)
        timeline.append({"session_id": sch.id, "start": s_start.astimezone(timezone.utc).isoformat(),
                         "end": s_end.astimezone(timezone.utc).isoformat(), "demand": sch.demand,
                         "state": "scheduled", "task_text": sch.name})
    timeline.sort(key=lambda x: x["start"])

    break_marks, nudges = marks(db, sessions, now)

    meetings = [
        {"start": _iso(m.starts_at), "end": _iso(m.ends_at), "title": m.title}
        for m in db.query(CalendarCache).filter(
            CalendarCache.user_id == user.id,
            CalendarCache.starts_at < _naive(day_end), CalendarCache.ends_at > _naive(day_start)).all()
    ]

    today_buckets = _pressure_by_bucket(sessions, day_start)
    pressure = [
        {"t": (day_start + timedelta(minutes=i * BUCKET_MIN)).isoformat(), "v": v}
        for i, v in sorted(today_buckets.items())
        if day_start + timedelta(minutes=i * BUCKET_MIN) <= now
    ]

    # "Usual day": your own previous 28 days with data, middle half (25th-75th percentile).
    past_buckets: Dict[int, List[float]] = {}
    past_focus: List[int] = []
    for back in range(1, 29):
        pd = d - timedelta(days=back)
        ps, pe = day_bounds(pd, tz)
        p_sessions = sessions_between(db, user.id, ps, pe)
        b = _pressure_by_bucket(p_sessions, ps)
        if not b:
            continue
        past_focus.append(sum(session_summary(db, s)["focus_minutes"] for s in p_sessions))
        for i, v in b.items():
            past_buckets.setdefault(i, []).append(v)
    usual_days = len(past_focus)
    usual_band = []
    if usual_days >= USUAL_DAYS_NEEDED:
        for i, vals in sorted(past_buckets.items()):
            if len(vals) >= 2:
                q = quantiles(vals, n=4)
                usual_band.append({"t": (day_start + timedelta(minutes=i * BUCKET_MIN)).isoformat(),
                                   "lo": round(q[0], 3), "hi": round(q[2], 3)})

    taken = sum(s["breaks_taken"] for s in summaries)
    suggested = sum(s["breaks_suggested"] for s in summaries)
    return {
        "date": d.isoformat(),
        "sessions": timeline,
        "breaks": break_marks,
        "nudges": nudges,
        "meetings": meetings,
        "pressure": pressure,
        # No model predicts pressure ahead yet, so no forecast line rather than a made-up one.
        "forecast": [],
        "forecast_band": [],
        "forecast_confidence": None,
        "usual_band": usual_band,
        "usual_days": usual_days if usual_days >= USUAL_DAYS_NEEDED else 0,
        "totals": {
            "focus_minutes": sum(s["focus_minutes"] for s in summaries),
            "usual_focus_minutes": round(median(past_focus)) if usual_days >= USUAL_DAYS_NEEDED else None,
            "breaks_taken": taken,
            "breaks_suggested": suggested,
            "breaks_skipped": max(0, suggested - taken),
        },
    }


# ── month view ───────────────────────────────────────────

def month(db: DBSession, user: User, year: int, mon: int) -> dict:
    tz = user_tz(db, user.id)
    first = date(year, mon, 1)
    nxt = date(year + (mon == 12), mon % 12 + 1, 1)
    start, _ = day_bounds(first, tz)
    end, _ = day_bounds(nxt, tz)
    per_day: Dict[str, int] = {}
    for s in sessions_between(db, user.id, start, end):
        local_day = _aware(s.start_time).astimezone(tz).date().isoformat()
        per_day[local_day] = per_day.get(local_day, 0) + session_summary(db, s)["focus_minutes"]
    return {"days": [{"date": k, "focus_minutes": v} for k, v in sorted(per_day.items()) if v > 0]}
