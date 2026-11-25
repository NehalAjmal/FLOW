# Task 3: break tracking (start/end, ratings, restoration, resumption lag).
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models  # noqa: registers every table
from db_models.base import Base, get_db
from db_models.breaks import Break
from db_models.rating import Rating
from db_models.session import Session
from db_models.user import User
from auth.dependencies import get_current_user
from breaks_app import router as breaks_router_module
from breaks_app import service
from interventions import service as intervention_service
from migrations import add_break_columns

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


def tick(at, keystrokes=20, switches=1, idle=3):
    return {"at": at.isoformat(), "keystrokes": keystrokes, "switches": switches, "idle": idle}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id="u1", full_name="Me", email="me@example.com", password_hash="x"),
        User(id="u2", full_name="Someone Else", email="else@example.com", password_hash="x"),
        Session(id="s1", user_id="u1", start_time=NOW - timedelta(hours=1),
                declared_difficulty="moderate", signal_log=[]),
        Session(id="s2", user_id="u2", start_time=NOW, signal_log=[]),
    ])
    db.commit()
    yield db
    db.close()


@pytest.fixture
def live_calls(monkeypatch):
    seen = []
    monkeypatch.setattr(breaks_router_module, "_live", lambda action, sid: seen.append((action, sid)))
    return seen


@pytest.fixture
def client(db, live_calls):
    app = FastAPI()
    app.include_router(breaks_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, "u1")
    return TestClient(app)


# ── start / end ──────────────────────────────────────────

def test_start_and_end_a_break(client, db, live_calls):
    r = client.post("/breaks/start", json={"session_id": "s1"})
    assert r.status_code == 200
    break_id = r.json()["break_id"]
    assert intervention_service.gate_for_user(db, "u1", datetime.now(timezone.utc)).reason == "on_break"

    r = client.post(f"/breaks/{break_id}/end", json={"actual_minutes": 5})
    assert r.status_code == 200
    b = db.get(Break, break_id)
    assert b.ended_at is not None and b.duration_actual_min == 5
    assert ("reset_ultradian", "s1") in live_calls          # ultradian clock restarts
    assert intervention_service.gate_for_user(db, "u1", datetime.now(timezone.utc)).allowed


def test_only_one_break_at_a_time(client):
    client.post("/breaks/start", json={"session_id": "s1"})
    assert client.post("/breaks/start", json={"session_id": "s1"}).status_code == 409


def test_cannot_end_twice(client):
    bid = client.post("/breaks/start", json={"session_id": "s1"}).json()["break_id"]
    client.post(f"/breaks/{bid}/end", json={})
    assert client.post(f"/breaks/{bid}/end", json={}).status_code == 409


def test_break_from_a_prompt_counts_as_suggested_and_taken(client, db):
    prompt = intervention_service.record_intervention(db, db.get(Session, "s1"), "trough", {}, 50.0, NOW)
    client.post("/breaks/start", json={"session_id": "s1", "intervention_id": prompt.id})
    summary = client.get("/breaks", params={"session_id": "s1"}).json()
    assert summary["suggested"] == 1 and summary["taken"] == 1
    assert summary["breaks"][0]["intervention_id"] == prompt.id


def test_someone_elses_session_or_break_is_404(client, db):
    assert client.post("/breaks/start", json={"session_id": "s2"}).status_code == 404
    other = service.start_break(db, db.get(Session, "s2"), None, NOW)
    assert client.post(f"/breaks/{other.id}/end", json={}).status_code == 404
    assert client.get("/breaks", params={"session_id": "s2"}).status_code == 404


# ── ratings ──────────────────────────────────────────────

def test_ratings(client, db):
    assert client.post("/ratings", json={"session_id": "s1", "kind": "post_break_focus",
                                         "value": 4, "context_id": "b1"}).status_code == 200
    assert db.query(Rating).count() == 1
    assert client.post("/ratings", json={"session_id": "s1", "kind": "focus", "value": 6}).status_code == 422
    assert client.post("/ratings", json={"session_id": "s1", "kind": "mood", "value": 3}).status_code == 422


# ── restoration + resumption lag ─────────────────────────

def _break_with_log(db, before_ticks, after_ticks, gap_minutes=5):
    """Distracted or focused ticks before a break at NOW, then ticks after it ends."""
    session = db.get(Session, "s1")
    start = NOW
    end = NOW + timedelta(minutes=gap_minutes)
    log = [tick(start - timedelta(seconds=30 * (len(before_ticks) - i)), **t) for i, t in enumerate(before_ticks)]
    session.signal_log = log
    db.commit()
    b = service.start_break(db, session, None, start)
    service.end_break(db, b, None, end)
    session.signal_log = log + [tick(end + timedelta(seconds=30 * (i + 1)), **t) for i, t in enumerate(after_ticks)]
    service.update_pending(db, session)
    db.commit()
    return b


DISTRACTED = dict(keystrokes=2, switches=7, idle=20)
FOCUSED = dict(keystrokes=25, switches=0, idle=2)


def test_restoration_high_when_focus_comes_back(db):
    b = _break_with_log(db, [DISTRACTED] * 6, [FOCUSED] * 6)
    assert b.restoration_score > 0.7
    assert b.duration_actual_min == 5


def test_restoration_low_when_still_distracted_after(db):
    b = _break_with_log(db, [FOCUSED] * 6, [DISTRACTED] * 6)
    assert b.restoration_score < 0.3


def test_restoration_waits_for_enough_ticks(db):
    b = _break_with_log(db, [DISTRACTED] * 6, [FOCUSED] * 3)
    assert b.restoration_score is None          # only 1.5 min of data after the break


def test_resumption_lag_from_log(db):
    idle = dict(keystrokes=0, switches=0, idle=30)
    b = _break_with_log(db, [FOCUSED] * 6, [idle, idle, FOCUSED])
    assert b.resumption_lag_sec == 90 and b.resumption_source == "log"


def test_agent_resumption_wins(client, db):
    b = _break_with_log(db, [FOCUSED] * 6, [FOCUSED] * 6)
    r = client.post("/session/s1/resumption", json={"break_id": b.id, "seconds_to_first_edit": 38})
    assert r.status_code == 200
    db.refresh(b)
    assert b.resumption_lag_sec == 38 and b.resumption_source == "agent"


# ── migration for databases created before Task 3 ────────

def test_migration_adds_missing_columns_and_is_safe_to_rerun():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:      # an old-style breaks table without the new columns
        conn.execute(text("CREATE TABLE breaks (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36))"))
    assert set(add_break_columns.run(engine)) == {"ended_at", "intervention_id",
                                                  "resumption_lag_sec", "resumption_source"}
    assert add_break_columns.run(engine) == []
