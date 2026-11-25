# Task 5 (part 2): dashboard, patterns, forecast, day and month views.
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models  # noqa: registers every table
from db_models.base import Base, get_db
from db_models.breaks import Break
from db_models.calendar_cache import CalendarCache
from db_models.schedule import Schedule
from db_models.session import Session
from db_models.user import User
from auth.dependencies import get_current_user
from insights import service
from insights.router import router as insights_router
from interventions import service as intervention_service

# Tuesday 24 Nov 2026, 10:00 UTC = 15:30 in India
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
LEARNED = {"parameters": {"ultradian_cycle_minutes": 60, "_session_lengths": [55, 60, 65, 60, 60],
                          "fatigue_focus_profile": {"9": 0.9, "10": 1.0, "15": 0.2}}}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(User(id="u1", full_name="Me", email="me@example.com", password_hash="x"))
    db.commit()
    intervention_service.get_settings(db, "u1").timezone = "Asia/Kolkata"
    db.commit()
    yield db
    db.close()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(insights_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, "u1")
    return TestClient(app)


def add_session(db, sid, start, minutes=50, ended=True, log=None):
    s = Session(id=sid, user_id="u1", start_time=start,
                end_time=start + timedelta(minutes=minutes) if ended else None,
                declared_difficulty="moderate", planned_duration_min=minutes,
                task_description="Write", signal_log=log or [])
    db.add(s)
    db.commit()
    return s


def ticks(start, minutes, score):
    return [{"at": (start + timedelta(minutes=m)).isoformat(), "score": score} for m in range(minutes)]


def finish_five(db):
    for i in range(5):
        add_session(db, f"old{i}", NOW - timedelta(days=i + 1))
    db.get(User, "u1").pattern_model = LEARNED
    db.commit()


# ── patterns ─────────────────────────────────────────────

def test_patterns_still_learning(client, db):
    add_session(db, "s1", NOW - timedelta(days=1))
    assert client.get("/user/patterns").json() == {"sessions_completed": 1, "sessions_needed": 4}


def test_patterns_after_five_sessions(client, db):
    finish_five(db)
    db.add(Break(session_id="old0", taken=True, taken_at=NOW, restoration_score=0.7))
    db.add(Break(session_id="old1", taken=True, taken_at=NOW, restoration_score=0.5))
    db.commit()
    p = client.get("/user/patterns").json()
    assert p["sessions_needed"] == 0
    assert p["peak_hours"] == {"value": [9, 10], "sample_size": 5, "confidence": "medium"}
    assert p["personal_period_min"]["value"] == 60
    assert p["break_effectiveness"] == {"value": 0.6, "sample_size": 2, "confidence": "low"}


def test_placeholder_cycle_is_not_reported(db):
    user = db.get(User, "u1")
    user.pattern_model = {"parameters": {"ultradian_cycle_minutes": 90, "_session_lengths": [40]}}
    assert service.learned_cycle(user) is None        # 90 is the learner's default, not a measurement


# ── forecast ─────────────────────────────────────────────

def test_forecast_unavailable_until_enough_data(client, db):
    f = client.get("/forecast").json()
    assert f["available"] is False and f["sessions_needed"] == 5 and f["windows"] == []


def test_forecast_follows_cycle_and_calendar(db):
    finish_five(db)
    db.add(CalendarCache(user_id="u1", event_id="m", title="Standup",
                         starts_at=NOW + timedelta(minutes=90), ends_at=NOW + timedelta(minutes=120)))
    db.commit()
    f = service.forecast(db, db.get(User, "u1"), NOW)
    kinds = [(w["kind"], w["start"][11:16], w["end"][11:16]) for w in f["windows"]]
    # focus 60 min, 5 min break, focus until the meeting, meeting, then focus again
    assert kinds[:4] == [("focus", "10:00", "11:00"), ("break", "11:00", "11:05"),
                         ("focus", "11:05", "11:30"), ("meeting", "11:30", "12:00")]
    assert f["available"] and "60-min focus cycle" in f["basis"] and "calendar" in f["basis"]


# ── dashboard ────────────────────────────────────────────

def test_dashboard_today_and_state(db):
    s = add_session(db, "now", NOW - timedelta(minutes=55), ended=False)
    finish_five(db)
    d = service.dashboard(db, db.get(User, "u1"), NOW)
    assert d["today"]["sessions"] == 1
    assert d["current_state"] == "approaching_break"       # 55 of 60 min
    assert d["quick_start"] == {"demand": "moderate", "minutes": 50, "task_text": "Write"}


def test_dashboard_new_user(client):
    d = client.get("/user/dashboard").json()
    assert d["today"] == {"sessions": 0, "focus_minutes": 0, "breaks_taken": 0}
    assert d["current_state"] is None and d["quick_start"] is None
    assert d["forecast"]["available"] is False


def test_paused_state(db):
    add_session(db, "now", NOW - timedelta(minutes=5), ended=False)
    intervention_service.get_settings(db, "u1").paused_until = NOW + timedelta(minutes=30)
    db.commit()
    assert service.current_state(db, db.get(User, "u1"), NOW) == "paused"


# ── day view ─────────────────────────────────────────────

def test_day_view(db):
    start = NOW - timedelta(hours=2)
    s = add_session(db, "s1", start, minutes=60, log=ticks(start, 60, 50.0))     # score 50 = on the nudge line
    p1 = intervention_service.record_intervention(db, s, "trough", {}, 40.0, start + timedelta(minutes=30))
    p1.response = "snoozed"
    p2 = intervention_service.record_intervention(db, s, "distracted", {}, 40.0, start + timedelta(minutes=50))
    p2.response = "accepted"
    db.add(Break(session_id="s1", taken=True, taken_at=start + timedelta(minutes=51),
                 ended_at=start + timedelta(minutes=56), duration_actual_min=5))
    db.add(Schedule(user_id="u1", name="Review", start="18:00", end="18:30", weekdays=[2],
                    demand="light", created_at=NOW))
    db.commit()

    d = service.day(db, db.get(User, "u1"), date(2026, 11, 24), NOW)
    assert [x["state"] for x in d["sessions"]] == ["done", "scheduled"]
    assert d["sessions"][1]["task_text"] == "Review"
    assert {b["mark"] for b in d["breaks"]} == {"taken", "snoozed"}
    assert [n["outcome"] for n in d["nudges"]] == ["snoozed", "taken"]
    assert d["pressure"] and all(p["v"] == 1.0 for p in d["pressure"])
    assert d["forecast"] == [] and d["usual_days"] == 0 and d["usual_band"] == []
    assert d["totals"]["breaks_suggested"] == 1 and d["totals"]["breaks_taken"] == 1


def test_usual_band_after_five_days(db):
    for back in range(1, 6):
        st = NOW - timedelta(days=back)
        add_session(db, f"p{back}", st, minutes=30, log=ticks(st, 30, 50.0 + back * 5))
    d = service.day(db, db.get(User, "u1"), date(2026, 11, 24), NOW)
    assert d["usual_days"] == 5 and d["usual_band"]
    band = d["usual_band"][0]
    assert band["lo"] <= band["hi"]
    assert d["totals"]["usual_focus_minutes"] == 30


# ── month view ───────────────────────────────────────────

def test_month(client, db):
    add_session(db, "a", datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc), minutes=40)
    add_session(db, "b", datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc), minutes=20)
    add_session(db, "c", datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc), minutes=20)
    r = client.get("/user/month", params={"month": "2026-11"}).json()
    assert r == {"days": [{"date": "2026-11-03", "focus_minutes": 60}]}
    assert client.get("/user/month", params={"month": "2026-13"}).status_code == 422
