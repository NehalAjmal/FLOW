# Task 5 (part 1): session history, replay, schedules.
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models  # noqa: registers every table
from db_models.base import Base, get_db
from db_models.breaks import Break
from db_models.session import Session
from db_models.user import User
from auth.dependencies import get_current_user
from history.router import router as history_router
from history.service import PAGE_SIZE, learned_lines
from interventions import service as intervention_service
from schedules.router import router as schedules_router

T0 = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id="u1", full_name="Me", email="me@example.com", password_hash="x"),
        User(id="u2", full_name="Someone Else", email="else@example.com", password_hash="x"),
    ])
    db.commit()
    yield db
    db.close()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(history_router)
    app.include_router(schedules_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, "u1")
    return TestClient(app)


def add_session(db, sid, user="u1", start=T0, minutes=60, **kw):
    s = Session(id=sid, user_id=user, start_time=start, end_time=start + timedelta(minutes=minutes),
                task_description=kw.get("task", "Write report"), declared_difficulty="heavy",
                planned_duration_min=50, signal_log=kw.get("log", []), learned_updates=kw.get("learned"))
    db.add(s)
    db.commit()
    return s


# ── history ──────────────────────────────────────────────

def test_summary_subtracts_break_time(client, db):
    s = add_session(db, "s1", minutes=60)
    p = intervention_service.record_intervention(db, s, "trough", {"title": "Dip"}, 50.0, T0 + timedelta(minutes=40))
    db.add(Break(session_id="s1", taken=True, taken_at=T0 + timedelta(minutes=41),
                 ended_at=T0 + timedelta(minutes=51), duration_actual_min=10, intervention_id=p.id))
    db.commit()
    item = client.get("/sessions").json()["items"][0]
    assert item["focus_minutes"] == 50                   # 60 in session - 10 on break
    assert item["breaks_suggested"] == 1 and item["breaks_taken"] == 1
    assert item["demand"] == "heavy" and item["task_text"] == "Write report"


def test_paging_and_only_my_sessions(client, db):
    for i in range(PAGE_SIZE + 3):
        add_session(db, f"s{i}", start=T0 - timedelta(hours=i))
    add_session(db, "theirs", user="u2")
    first = client.get("/sessions").json()
    assert len(first["items"]) == PAGE_SIZE and first["has_more"] is True
    second = client.get("/sessions", params={"page": 2}).json()
    assert len(second["items"]) == 3 and second["has_more"] is False
    ids = {i["session_id"] for i in first["items"] + second["items"]}
    assert "theirs" not in ids
    assert first["items"][0]["session_id"] == "s0"        # newest first


def test_date_filter_is_inclusive(client, db):
    add_session(db, "today", start=T0)
    add_session(db, "yesterday", start=T0 - timedelta(days=1))
    add_session(db, "last_week", start=T0 - timedelta(days=7))
    r = client.get("/sessions", params={"from": "2026-11-23", "to": "2026-11-24"}).json()
    assert {i["session_id"] for i in r["items"]} == {"today", "yesterday"}


def test_replay_timeline(client, db):
    log = [{"at": (T0 + timedelta(minutes=m)).isoformat(), "state": st}
           for m, st in [(1, "deep_work"), (2, "deep_work"), (20, "distracted"), (30, "deep_work")]]
    s = add_session(db, "s1", log=log, learned={"ultradian_cycle_minutes": 82, "trough_minute": 40,
                                                "sessions_in_model": 6})
    p = intervention_service.record_intervention(db, s, "distracted", {"title": "Attention scattering"}, 40.0,
                                                 T0 + timedelta(minutes=26))
    p.response = "dismissed"
    db.add(Break(session_id="s1", taken=True, taken_at=T0 + timedelta(minutes=45),
                 ended_at=T0 + timedelta(minutes=50), duration_actual_min=5, resumption_lag_sec=38))
    db.commit()

    r = client.get("/session/s1/replay").json()
    kinds = [(e["minute"], e["kind"]) for e in r["events"]]
    assert kinds == [(0.0, "start"), (20.0, "state"), (26.0, "nudge"), (30.0, "state"),
                     (45.0, "break"), (50.0, "break_end"), (60.0, "end")]
    texts = " | ".join(e["text"] for e in r["events"])
    assert "deep work → distracted" in texts and "you dismissed it" in texts and "38 s later" in texts
    assert r["what_flow_learned"] == [
        "Your focus cycle estimate is now 82 min (from 6 sessions).",
        "Your focus usually dips around minute 40 (from 6 sessions).",
    ]


def test_replay_of_someone_elses_session_is_404(client, db):
    add_session(db, "theirs", user="u2")
    assert client.get("/session/theirs/replay").status_code == 404


def test_learned_lines_never_invent():
    assert learned_lines(None) == []
    assert learned_lines({"ultradian_cycle_minutes": None, "trough_minute": None}) == []


# ── schedules ────────────────────────────────────────────

REVIEW = {"name": "Weekly review", "start": "17:40", "end": "18:20",
          "weekdays": [5, 1, 1], "demand": "light", "enabled": True}


def test_schedule_crud(client):
    created = client.post("/user/schedules", json=REVIEW).json()
    assert created["id"] and created["weekdays"] == [1, 5]          # sorted, no duplicates
    assert client.get("/user/schedules").json()["schedules"] == [created]

    changed = client.put(f"/user/schedules/{created['id']}", json={**REVIEW, "enabled": False}).json()
    assert changed["enabled"] is False

    assert client.delete(f"/user/schedules/{created['id']}").status_code == 204
    assert client.get("/user/schedules").json()["schedules"] == []


def test_schedule_validation(client):
    for bad in ({"end": "17:00"}, {"start": "25:00"}, {"weekdays": []}, {"weekdays": [8]},
                {"demand": "extreme"}, {"name": ""}):
        assert client.post("/user/schedules", json={**REVIEW, **bad}).status_code == 422, bad


def test_cannot_touch_someone_elses_schedule(client, db):
    from db_models.schedule import Schedule
    theirs = Schedule(user_id="u2", created_at=T0, **{k: v for k, v in REVIEW.items()})
    db.add(theirs)
    db.commit()
    assert client.put(f"/user/schedules/{theirs.id}", json=REVIEW).status_code == 404
    assert client.delete(f"/user/schedules/{theirs.id}").status_code == 404
    assert client.get("/user/schedules").json()["schedules"] == []
