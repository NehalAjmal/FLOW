from typing import Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session as DBSession

from db_models.user import User
from db_models.session import Session
from db_models.biometric import BiometricReading
from llm.cache import get_intervention

#  ML ENGINE IMPORTS
from engine.decision import DecisionEngine, compute_trough_pressure
from engine.deviation import DeviationEngine
from engine.ultradian import UltradianEngine
from engine.biometric import BiometricEngine
import subprocess
import os
import sys
from learning.engine import PatternLearner
from interventions.service import PROMPT_STATES, gate_for_user, record_intervention
from breaks_app import service as breaks_service
from db_models.breaks import Break
 

#  FATIGUE SERVICE
from ml_models.fatigue_model import fatigue_service

_live_sessions: dict = {}

# The agent sends a tick every 30s; the log covers ~5h before capping.
AGENT_TICK_MINUTES = 0.5
SIGNAL_LOG_CAP = 600

PASSIVE_APPS = {
    "youtube", "netflix", "twitter", "instagram", "facebook",
    "reddit", "tiktok", "twitch", "spotify", "discord"
}

DEFAULT_TROUGH_MINUTE = 45
DEFAULT_ULTRADIAN_CYCLE = 90


# ── FALLBACK LOGIC (DO NOT REMOVE) ─────────────────────────

def classify_state(kpm, switches, idle, window, minutes):
    if any(p in window.lower() for p in PASSIVE_APPS):
        return "passive"
    if minutes >= 90 and kpm < 10:
        return "fatigue"
    if switches <= 2 and kpm < 8:
        return "stuck"
    return "deep_work"


def compute_focus_score(kpm, switches, idle, minutes, state):
    if state == "passive":
        return max(0.0, 30.0 - (idle / 10))
    if state == "fatigue":
        return max(10.0, 60.0 - (minutes - 90) * 0.5)
    if state == "stuck":
        return 35.0
    return min(100.0, kpm * 1.2 + 20)


# ── HELPERS ────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """MySQL returns naive datetimes; treat stored values as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _new_engines() -> dict:
    """Fresh engine set per session — no state leaks across users/sessions."""
    return {
        "decision": DecisionEngine(),
        "deviation": DeviationEngine(),
        "ultradian": UltradianEngine(),
        "biometric": BiometricEngine(),
    }


def _learned_params(db: DBSession, user_id: str) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.pattern_model:
        return {}
    return user.pattern_model.get("parameters", {}) or {}


def _latest_hr_hrv(db: DBSession, session_id: str):
    """Latest real heart-rate signal for this session: DB readings first
    (Apple Watch / rPPG ingest), then the live webcam rPPG estimate."""
    row = (
        db.query(BiometricReading)
        .filter(BiometricReading.session_id == session_id)
        .order_by(BiometricReading.recorded_at.desc())
        .first()
    )
    if row and row.heart_rate_bpm and row.hrv_sdnn:
        return float(row.heart_rate_bpm), float(row.hrv_sdnn)

    # live webcam rPPG (same process) — HR only, gated by confidence
    state = fatigue_service.get_state()
    hr = state.get("heart_rate_bpm")
    if hr and state.get("hr_confidence", 0.0) >= 0.15:
        return float(hr), None
    return None


# ── START SESSION ─────────────────────────────────────────

def start_session(
    db: DBSession,
    user_id: str,
    task_description: str,
    declared_difficulty: str,
    planned_duration_min: int,
):
    session = Session(
        user_id=user_id,
        task_description=task_description,
        declared_difficulty=declared_difficulty,
        planned_duration_min=planned_duration_min,
        start_time=_utcnow(),
        signal_log=[],
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    params = _learned_params(db, user_id)
    cycle_minutes = int(params.get("ultradian_cycle_minutes") or params.get("ultradian_period") or DEFAULT_ULTRADIAN_CYCLE)

    #  PER-SESSION ENGINES (ultradian clock starts now)
    engines = _new_engines()
    engines["ultradian"] = UltradianEngine(cycle_minutes=cycle_minutes)
    engines["ultradian"].start()

    #  START FATIGUE TRACKING (CAMERA OPENS HERE ONLY IF GRANTED)
    from settings_app.service import feature_allowed
    camera_allowed = feature_allowed(db, user_id, "camera")   # consent AND the Settings switch
    if camera_allowed:
        try:
            fatigue_service.start()
        except Exception as e:
            print("fatigue start failed:", e)
    else:
        print(f"[Privacy] Camera consent not granted for user {user_id}. Webcam disabled.")

    #  START KEYBOARD/MOUSE LOCAL AGENT WITH AUTH TOKEN
    agent_process = None
    try:
        from auth.utils import create_access_token
        agent_token = create_access_token(data={"sub": user_id, "role": "agent"}, expires_delta=timedelta(hours=24))
        agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent"))
        token_path = os.path.join(agent_dir, ".agent_token")
        try:
            with open(token_path, "w") as f:
                f.write(agent_token)
        except Exception:
            pass

        agent_script = os.path.abspath(os.path.join(agent_dir, "main.py"))
        agent_process = subprocess.Popen([sys.executable, agent_script, session.id, agent_token])
    except Exception as e:
        print("Agent start failed:", e)

    _live_sessions[session.id] = {
        "state": "deep_work",
        "focus_score": 75.0,
        "minutes_in_state": 0,
        "session_start": _utcnow(),
        "intervention": None,
        "agent_process": agent_process,
        "engines": engines,
        "user_id": user_id,
        "trough_minute": int(params.get("trough_minute") or DEFAULT_TROUGH_MINUTE),
    }

    return session


def verify_session_ownership(db: DBSession, session_id: str, user_id: str) -> Session:
    """
    Verify that the session exists and belongs to user_id.
    Prevents IDOR across all session endpoints.
    """
    from fastapi import HTTPException
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this session")
    return session


def _rehydrate_live(db: DBSession, session: Session) -> dict:
    """
    Rebuild an in-memory live entry from the DB row.
    Needed after a server restart (or uvicorn --reload) while a session runs —
    otherwise every agent tick fails and the session is orphaned.
    """
    params = _learned_params(db, session.user_id)
    cycle_minutes = int(params.get("ultradian_cycle_minutes") or params.get("ultradian_period") or DEFAULT_ULTRADIAN_CYCLE)

    engines = _new_engines()
    start = _as_aware_utc(session.start_time) or _utcnow()
    # Resume the ultradian clock from the last break's end, or the session start
    last_break = (
        db.query(Break)
        .filter(Break.session_id == session.id, Break.ended_at.isnot(None))
        .order_by(Break.ended_at.desc())
        .first()
    )
    clock_from = _as_aware_utc(last_break.ended_at) if last_break else start
    engines["ultradian"] = UltradianEngine(cycle_minutes=cycle_minutes)
    engines["ultradian"].start_time = clock_from.timestamp()

    live = {
        "state": "deep_work",
        "focus_score": 75.0,
        "minutes_in_state": 0,
        "session_start": start,
        "intervention": None,
        "agent_process": None,
        "engines": engines,
        "user_id": session.user_id,
        "trough_minute": int(params.get("trough_minute") or DEFAULT_TROUGH_MINUTE),
        "rehydrated": True,
    }
    _live_sessions[session.id] = live
    return live


# ── INGEST SIGNAL (MAIN LOGIC) ─────────────────────────

def ingest_signal(
    db,
    session_id,
    keystroke_count,
    window_switches,
    idle_seconds,
    mouse_distance_px,
    active_window,
    timestamp,
):
    live = _live_sessions.get(session_id)

    # ── DB SESSION ───────────────────────────
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        return None  # truly unknown session → router returns 404

    if session.end_time is not None:
        # Session already ended — ignore stale agent ticks (agent exits on 404)
        return None

    if not live:
        # Server restarted mid-session: rebuild state instead of erroring out
        live = _rehydrate_live(db, session)
        print(f" rehydrated live session {session_id[:8]} from DB")

    # ── TIME CALCULATION ─────────────────────
    session_minutes = int(
        (_utcnow() - live["session_start"]).total_seconds() / 60
    )

    kpm = keystroke_count * 2

    #  TROUGH CALCULATION — real elapsed minutes vs the user's learned trough
    current_minute = session_minutes
    trough_minute = live["trough_minute"]

    trough_pressure = 0.0

    try:
        # ── ML SIGNALS ─────────────────────────
        engines = live["engines"]
        deviation = engines["deviation"].compute(
            keystrokes=keystroke_count,
            switches=window_switches,
            idle_seconds=idle_seconds,
            declared_difficulty=session.declared_difficulty or "moderate",
        )
        ultradian = engines["ultradian"].compute()

        fatigue = fatigue_service.get_state().get("fatigue_score")

        # Use measured biometric data only; never substitute fatigue as a proxy.
        hr_hrv = _latest_hr_hrv(db, session_id)
        if hr_hrv and hr_hrv[1] is not None:
            biometric = engines["biometric"].compute(
                hr=hr_hrv[0],
                hrv=hr_hrv[1],
            )
        else:
            biometric = None

        #  TROUGH PRESSURE
        trough_pressure = compute_trough_pressure(current_minute, trough_minute)

        # ── DECISION ENGINE ────────────────────
        decision = engines["decision"].compute(
            fatigue=fatigue,
            deviation=deviation,
            ultradian=ultradian,
            biometric=biometric,
            trough_pressure=trough_pressure
        )

        new_state = decision["state"]
        focus_score = decision["focus_score"]
        new_score = (
            round(focus_score * 100, 2)
            if focus_score is not None
            else None
        )

        if new_score is None:
            raise ValueError("Cannot score session: no signals available")

    except Exception as e:
        print(" fallback:", e)

        new_state = classify_state(kpm, window_switches, idle_seconds, active_window, session_minutes)
        new_score = compute_focus_score(kpm, window_switches, idle_seconds, session_minutes, new_state)

        deviation = ultradian = biometric = fatigue = 0.0

    # ── STATE TRACKING ───────────────────────
    if new_state == live["state"]:
        live["minutes_in_state"] += AGENT_TICK_MINUTES
    else:
        live["minutes_in_state"] = 0
        live["intervention"] = None

    live.update({
        "state": new_state,
        "focus_score": new_score,
        "keystrokes_per_min": kpm,
        "window_switches": window_switches,
        "idle_seconds": idle_seconds,
        "active_window": active_window,
    })

     #  INTERVENTION: pick a candidate, then let gating decide
    candidate_kind, candidate = None, None
    if trough_pressure > 0.8:
        candidate_kind = "trough"
        candidate = {
            "title": "Upcoming focus dip",
            "message": "You're nearing a natural dip in focus. Consider taking a break.",
            "action_label": "Take Break"
        }

    elif live["minutes_in_state"] > 5 and new_state in PROMPT_STATES:
        candidate_kind = new_state
        candidate = get_intervention(new_state)

    live["gate_reason"] = None
    if candidate and not live["intervention"]:
        now = _utcnow()
        gate = gate_for_user(db, live["user_id"], now)
        if gate.allowed:
            row = record_intervention(db, session, candidate_kind, candidate, new_score, now)
            live["intervention"] = {**candidate, "id": row.id, "kind": candidate_kind}
        else:
            live["gate_reason"] = gate.reason   # e.g. "quiet_hours"; handy when debugging

    # ── DB LOG ───────────────────────────────
    # FIX: list() creates a NEW object so SQLAlchemy detects the change.
    # Previously, append() mutated the tracked list in-place → ORM saw
    # old value == new value → no UPDATE was emitted after the first tick.
    log = list(session.signal_log or [])

    log.append({
        "ts": timestamp,
        "at": _utcnow().isoformat(),   # server time (UTC); breaks use it to find before/after ticks
        "keystrokes": keystroke_count,
        "switches": window_switches,
        "idle": idle_seconds,
        "window": active_window,
        "state": new_state,
        "score": round(new_score, 1),

        "fatigue": fatigue,
        "deviation": deviation,
        "ultradian": ultradian,
        "biometric": biometric
    })

    session.signal_log = log[-SIGNAL_LOG_CAP:]
    breaks_service.update_pending(db, session)   # restoration + resumption lag, once there's data
    db.commit()

    return live


def drop_live_session(session_id: str) -> None:
    """Account deleted mid-session: stop the agent and camera, forget the live state."""
    live = _live_sessions.pop(session_id, None)
    if live and live.get("agent_process"):
        try:
            live["agent_process"].terminate()
        except Exception:
            pass
    try:
        fatigue_service.stop()
    except Exception:
        pass


def reset_ultradian(session_id: str) -> None:
    """A break just ended: the ultradian clock starts again from now."""
    live = _live_sessions.get(session_id)
    if live:
        live["engines"]["ultradian"].reset_after_break()


def clear_live_intervention(session_id: str) -> None:
    """Take the answered prompt off the live screen state."""
    live = _live_sessions.get(session_id)
    if live:
        live["intervention"] = None


def handle_intervention_response(db: DBSession, session_id: str, response: str):
    live = _live_sessions.get(session_id)
    if live:
        if response in ["dismissed", "accepted"]:
            live["intervention"] = None
    return {"status": "ok", "response": response}

# ── GET STATUS ─────────────────────────

def get_session_status(db: DBSession, session_id: str):
    """
    Returns live status for a session.
    Returns None when the session doesn't exist (router → 404).
    """
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        return None

    live = _live_sessions.get(session_id)
    fatigue = fatigue_service.get_state()

    def _minutes_to_trough() -> Optional[int]:
        """Minutes until the session's learned trough, or None when unknown."""
        if not live:
            return None
        start = _as_aware_utc(session.start_time) or live["session_start"]
        elapsed = int((_utcnow() - start).total_seconds() / 60)
        return max(0, live["trough_minute"] - elapsed)

    if not live:
        # Session exists but has no in-memory state (e.g. started before a restart):
        # report DB-derived basics instead of inventing a fake healthy session.
        log = session.signal_log or []
        return {
            "state": log[-1]["state"] if log else "deep_work",
            "focus_score": round(log[-1]["score"], 1) if log else 0.0,
            "signals": {
                "behavioral": 0.0,
                "ultradian": 0.5,
                "biometric": fatigue.get("fatigue_score", 0.0),
                "ear": min(1.0, fatigue.get("ear", 0.0) * 3),
            },
            "intervention": None,
            "minutes_to_trough": None,
        }

    engines = live.get("engines") or {}

    return {
        "state": live.get("state", "deep_work"),
        "focus_score": round(live.get("focus_score", 75), 1),
        "signals": {
            "behavioral": min(1.0, live.get("keystrokes_per_min", 0) / 40),
            "ultradian": engines["ultradian"].compute() if engines else 0.5,
            "biometric": fatigue.get("fatigue_score", 0.0),
            "ear": min(1.0, fatigue.get("ear", 0.0) * 3),
        },
        "heart_rate_bpm": fatigue.get("heart_rate_bpm"),
        "intervention": live.get("intervention"),
        "minutes_to_trough": _minutes_to_trough(),
    }

def _prepare_learning_data(signal_log):
    """
    Convert DB signal_log → PatternLearner format.
    Keys must match what learning/engine.py reads:
    keystroke_count / window_switches / idle_seconds.
    """

    data = []

    for entry in signal_log:
        data.append({
            "timestamp": entry.get("ts"),

            "input": {
                "keystroke_count": entry.get("keystrokes", 0),
                "window_switches": entry.get("switches", 0),
                "idle_seconds": entry.get("idle", 0),
            },

            "output": {
                "fatigue": entry.get("fatigue", 0.0),
                "deviation": entry.get("deviation", 0.0)
            }
        })

    return data

# ── END SESSION ─────────────────────────

def end_session(
    db: DBSession,
    session_id: str,
    self_rated_quality: Optional[int] = None,
):
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        return {"error": "not found"}

    session.end_time = _utcnow()
    session.self_rated_quality = self_rated_quality

    running = breaks_service.active_break(db, session_id)
    if running is not None:            # session ended mid-break: close the break too
        breaks_service.end_break(db, running, None, session.end_time)

    log = session.signal_log or []
    scores = [entry.get("score", 75) for entry in log]

    session.focus_score = int(sum(scores) / len(scores)) if scores else 75

    if session.actual_duration_min is None and session.start_time:
        start = _as_aware_utc(session.start_time)
        session.actual_duration_min = max(0, int((session.end_time - start).total_seconds() / 60))

    db.commit()

    live_data = _live_sessions.pop(session_id, None)
    if live_data and live_data.get("agent_process"):
        try:
            live_data["agent_process"].terminate()
            print("Stopped tracking agent.")
        except Exception:
            pass

    # Stop fatigue camera too since session ended
    try:
        fatigue_service.stop()
    except Exception:
        pass

    # ── PATTERN LEARNING (per-user, stateless) ─────────
    learning_data = _prepare_learning_data(log)
    user = db.query(User).filter(User.id == session.user_id).first()
    learner = PatternLearner()
    previous_model = user.pattern_model if user else {}
    patterns = learner.update(previous_model, learning_data)

    if user:
        user.pattern_model = patterns
    db.commit()

    print(f" learned patterns for session {session_id[:8]}: "
          f"trough={patterns.get('parameters', {}).get('trough_minute')} min, "
          f"cycle={patterns.get('parameters', {}).get('ultradian_cycle_minutes')} min")

    return {
        "session_id": session_id,
        "focus_score": session.focus_score,
        "actual_duration_min": session.actual_duration_min,
        "events": log[:20],
        "patterns": patterns
    }
