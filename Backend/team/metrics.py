# team/metrics.py
# Numbers about a team, worked out from stored sessions only.
# Used by /team/summary (every member sees it) and the /admin/* pages.
#
# Rules for this file:
#   * Only employees who granted the 'team_aggregate' consent are counted.
#   * Team-wide numbers are withheld (suppressed) below MIN_GROUP people.
#   * Never send task text, window titles, apps, typing or camera data.
#   * If there's not enough data for a number, send null, not a guess.

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean, median
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DBSession

from breaks_app.service import BREAK_PROMPT_KINDS
from consent.service import has_consent
from db_models.breaks import Break
from db_models.intervention import Intervention
from db_models.session import Session
from db_models.user import User
from history.service import session_summary
from insights.service import NUDGE_LINE_SCORE, _aware, _naive, user_tz

MIN_GROUP = 5                   # privacy floor for anything team-wide (contract section 7)
SUPPRESSED_REASON = "min_group_size_5"
ENOUGH_SESSIONS = 10            # sessions needed before peak hours / meeting window mean anything
ENOUGH_BREAKS = 5               # breaks needed before "typical recovery"
STRAIN_MODERATE = 0.15          # share of ticks under the nudge line that makes strain "moderate"
STRAIN_HIGH = 0.35              # ... and "high"
STALE_HOURS = 12                # an unfinished session older than this was abandoned, not live
WORK_HOURS = range(9, 17)       # meeting window candidates start 09:00 .. 16:00 local, Mon..Fri


# ── who counts ───────────────────────────────────────────

def members(db: DBSession, team_id: Optional[str]) -> List[User]:
    """Employees of the team who share with the team, by name."""
    if not team_id:
        return []
    people = (db.query(User)
              .filter(User.team_id == team_id, User.role == "employee")
              .order_by(User.full_name).all())
    return [u for u in people if has_consent(db, u.id, "team_aggregate")]


def wrap(group_size: int, build: Callable[[], Optional[dict]]) -> dict:
    """The one wrapper every team/admin endpoint uses: {group_size, suppressed, reason, metrics}.
    `build` only runs when the group is big enough, so suppressed numbers are never even computed."""
    if group_size < MIN_GROUP:
        return {"group_size": group_size, "suppressed": True, "reason": SUPPRESSED_REASON, "metrics": None}
    return {"group_size": group_size, "suppressed": False, "reason": None, "metrics": build()}


# ── time helpers ─────────────────────────────────────────

def local_date(dt: datetime, tz: ZoneInfo) -> date:
    return _aware(dt).astimezone(tz).date()


def week_start(now: datetime, tz: ZoneInfo) -> date:
    """Monday of this week, in the viewer's time zone."""
    today = now.astimezone(tz).date()
    return today - timedelta(days=today.weekday())


def utc_start(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)


def load_sessions(db: DBSession, user_ids: List[str], start: datetime, end: datetime) -> List[Session]:
    if not user_ids:
        return []
    return (db.query(Session)
            .filter(Session.user_id.in_(user_ids),
                    Session.start_time >= _naive(start), Session.start_time < _naive(end))
            .order_by(Session.start_time).all())


def is_live(s: Session, now: datetime) -> bool:
    return s.end_time is None and s.start_time is not None and \
        now - _aware(s.start_time) < timedelta(hours=STALE_HOURS)


def session_end(s: Session, now: datetime) -> datetime:
    """Where a session stops on a timeline. An unfinished one runs to now
    (or STALE_HOURS after its start, if it was abandoned)."""
    if s.end_time:
        return _aware(s.end_time)
    return min(now, _aware(s.start_time) + timedelta(hours=STALE_HOURS))


class Summaries:
    """session_summary() runs two queries, so remember each result.
    Unfinished sessions count up to `now`, and abandoned ones stop after STALE_HOURS."""

    def __init__(self, db: DBSession, now: datetime):
        self.db, self.now, self._cache = db, now, {}

    def __call__(self, s: Session) -> dict:
        if s.id not in self._cache:
            self._cache[s.id] = session_summary(self.db, s, until=session_end(s, self.now))
        return self._cache[s.id]


# ── per-day numbers ──────────────────────────────────────

def focus_by_date(sessions: List[Session], tz: ZoneInfo, summ: Summaries) -> Dict[date, int]:
    """Focus minutes per local day (a session counts on the day it started)."""
    out: Dict[date, int] = defaultdict(int)
    for s in sessions:
        out[local_date(s.start_time, tz)] += summ(s)["focus_minutes"]
    return out


def score_by_date(sessions: List[Session], tz: ZoneInfo) -> Dict[date, float]:
    """Mean finished-session focus score per day, as 0..1."""
    scores: Dict[date, List[float]] = defaultdict(list)
    for s in sessions:
        if s.focus_score is not None:
            scores[local_date(s.start_time, tz)].append(s.focus_score / 100)
    return {d: round(mean(v), 3) for d, v in scores.items()}


def tick_strain(sessions: List[Session]) -> Tuple[int, int]:
    """(ticks under the nudge line, all scored ticks). Break pressure, not a health measure."""
    over = total = 0
    for s in sessions:
        for e in s.signal_log or []:
            if e.get("score") is None:
                continue
            total += 1
            over += float(e["score"]) <= NUDGE_LINE_SCORE
    return over, total


def strain_by_date(sessions: List[Session], tz: ZoneInfo) -> Dict[date, float]:
    by_day: Dict[date, List[Session]] = defaultdict(list)
    for s in sessions:
        by_day[local_date(s.start_time, tz)].append(s)
    out = {}
    for d, ss in by_day.items():
        over, total = tick_strain(ss)
        if total:
            out[d] = round(over / total, 3)
    return out


def strain_level(over: int, total: int) -> str:
    share = over / total if total else 0.0
    return "high" if share >= STRAIN_HIGH else "moderate" if share >= STRAIN_MODERATE else "low"


def trend(values: Dict[date, float], days: List[date], fill_zero: bool = False) -> List[dict]:
    """[{date, value}] in date order. Days with no data are left out, unless
    zero is a real answer (focus minutes on a day with no sessions)."""
    out = []
    for d in days:
        if d in values:
            out.append({"date": d.isoformat(), "value": values[d]})
        elif fill_zero:
            out.append({"date": d.isoformat(), "value": 0})
    return out


def last_days(now: datetime, tz: ZoneInfo, n: int) -> List[date]:
    today = now.astimezone(tz).date()
    return [today - timedelta(days=n - 1 - i) for i in range(n)]


def focus_by_hour(sessions: List[Session], tz: ZoneInfo, now: datetime,
                  weekdays_only: bool = False) -> List[float]:
    """Minutes in a session in each local hour 0..23, summed over the sessions."""
    out = [0.0] * 24
    for s in sessions:
        t, end = _aware(s.start_time).astimezone(tz), session_end(s, now).astimezone(tz)
        while t < end:
            nxt = (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            upto = min(nxt, end)
            if not (weekdays_only and t.weekday() >= 5):
                out[t.hour] += (upto - t).total_seconds() / 60
            t = upto
    return out


# ── the team-wide numbers ────────────────────────────────

def peak_hours(sessions, tz, now) -> List[int]:
    """The three local hours with the most focus, in clock order. Empty until there's enough data."""
    if len(sessions) < ENOUGH_SESSIONS:
        return []
    by_hour = focus_by_hour(sessions, tz, now)
    top = sorted(range(24), key=lambda h: by_hour[h], reverse=True)[:3]
    return sorted(h for h in top if by_hour[h] > 0)


def meeting_window(sessions, tz, now) -> Optional[dict]:
    """The weekday working hour when the team is least often in focus.
    Replaces the old fixed '14:00 - 16:00'."""
    if len(sessions) < ENOUGH_SESSIONS:
        return None
    by_hour = focus_by_hour(sessions, tz, now, weekdays_only=True)
    best = min(WORK_HOURS, key=lambda h: (by_hour[h], h))
    return {"start": f"{best:02d}:00", "end": f"{best + 1:02d}:00"}


def typical_recovery_min(db: DBSession, sessions: List[Session]) -> Optional[int]:
    """Median length of the breaks people actually took (minutes)."""
    sids = [s.id for s in sessions]
    if not sids:
        return None
    lengths = [(_aware(b.ended_at) - _aware(b.taken_at)).total_seconds() / 60
               for b in db.query(Break).filter(Break.session_id.in_(sids)).all()
               if b.taken_at and b.ended_at]
    return round(median(lengths)) if len(lengths) >= ENOUGH_BREAKS else None


class TeamView:
    """Everything team-wide for one viewer, loaded once. Times are in the viewer's zone."""

    def __init__(self, db: DBSession, viewer: User, now: Optional[datetime] = None):
        self.db = db
        self.now = now or datetime.now(timezone.utc)
        self.tz = user_tz(db, viewer.id)
        self.people = members(db, viewer.team_id)
        self.ids = [u.id for u in self.people]
        self.summ = Summaries(db, self.now)
        self.monday = week_start(self.now, self.tz)

    @property
    def group_size(self) -> int:
        return len(self.people)

    def sessions_since(self, days: int) -> List[Session]:
        start = utc_start(self.now.astimezone(self.tz).date() - timedelta(days=days - 1), self.tz)
        return load_sessions(self.db, self.ids, start, self.now + timedelta(seconds=1))

    def week_sessions(self) -> List[Session]:
        return load_sessions(self.db, self.ids, utc_start(self.monday, self.tz), self.now + timedelta(seconds=1))

    def score_trend(self, days: int) -> List[dict]:
        return trend(score_by_date(self.sessions_since(days), self.tz), last_days(self.now, self.tz, days))

    def team_summary(self) -> dict:
        """metrics for /team/summary: team averages only, never a person."""
        week = self.week_sessions()
        focus = sum(self.summ(s)["focus_minutes"] for s in week)
        worked_days = {(s.user_id, local_date(s.start_time, self.tz)) for s in week}
        taken = sum(self.summ(s)["breaks_taken"] for s in week)
        suggested = sum(self.summ(s)["breaks_suggested"] for s in week)
        scores = [s.focus_score for s in self.sessions_since(7) if s.focus_score is not None]
        return {
            "average_focus": round(mean(scores) / 100, 3) if scores else None,
            "trend": self.score_trend(7),
            "focus_minutes_per_day": round(focus / len(worked_days)) if worked_days else None,
            "sessions_per_day": round(len(week) / len(worked_days), 2) if worked_days else None,
            "break_uptake": round(taken / suggested, 3) if suggested else None,
            "peak_hours": peak_hours(self.sessions_since(14), self.tz, self.now),
            "focus_minutes_this_week": round(focus / self.group_size),
        }

    def admin_summary(self) -> dict:
        week = self.week_sessions()
        live = sum(1 for s in self.sessions_since(1) if is_live(s, self.now))
        return {"active_count": live, "avg_focus_trend": self.score_trend(7), "session_volume": len(week)}

    def admin_trend(self) -> dict:
        return {"days_7": self.score_trend(7), "days_30": self.score_trend(30)}

    def admin_insights(self) -> dict:
        recent = self.sessions_since(14)
        return {"peak_hours": peak_hours(recent, self.tz, self.now),
                "typical_recovery_min": typical_recovery_min(self.db, self.sessions_since(30))}

    def admin_strain(self) -> dict:
        over, total = tick_strain(self.sessions_since(7))
        return {"level": strain_level(over, total), "note": self._strain_note()}

    def _strain_note(self) -> str:
        """Compare break suggestions in the last 7 days with the 7 before."""
        def count(days_back_start, days_back_end):
            q = self.db.query(Intervention).filter(
                Intervention.user_id.in_(self.ids), Intervention.kind.in_(BREAK_PROMPT_KINDS),
                Intervention.shown_at >= _naive(self.now - timedelta(days=days_back_start)),
                Intervention.shown_at < _naive(self.now - timedelta(days=days_back_end)))
            return q.count()
        this, last = count(7, 0), count(14, 7)
        if this == 0 and last == 0:
            return "No break suggestions in the last two weeks."
        if last == 0:
            return f"{this} break suggestions this week, none the week before."
        change = round((this - last) / last * 100)
        if change == 0:
            return "Break suggestions about the same as last week."
        return f"Break suggestions {'up' if change > 0 else 'down'} {abs(change)}% vs last week."

    def admin_meeting_window(self) -> Optional[dict]:
        return meeting_window(self.sessions_since(14), self.tz, self.now)
