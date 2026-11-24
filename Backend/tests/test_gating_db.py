# Gating against a real (throwaway, in-memory SQLite) database:
# settings rows, meetings, the 15-minute gap across sessions, and /pause + /settings.
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models  # noqa: registers every table
from db_models.base import Base, get_db
from db_models.user import User
from db_models.session import Session
from db_models.calendar_cache import CalendarCache
from auth.dependencies import get_current_user
from interventions import service
from settings_app.router import router as settings_router

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)   # 15:30 in India


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(User(id="u1", full_name="Test User", email="t@example.com", password_hash="x"))
    db.add(Session(id="s1", user_id="u1", start_time=NOW))
    db.commit()
    yield db
    db.close()


def test_new_user_gets_default_settings(db):
    s = service.get_settings(db, "u1")
    assert s.timezone == "UTC" and s.paused_until is None


def test_allowed_by_default(db):
    assert service.gate_for_user(db, "u1", NOW).allowed


def test_meeting_blocks(db):
    db.add(CalendarCache(user_id="u1", event_id="e1", title="Standup",
                         starts_at=NOW - timedelta(minutes=5), ends_at=NOW + timedelta(minutes=25)))
    db.commit()
    assert service.gate_for_user(db, "u1", NOW).reason == "in_meeting"


def test_meeting_that_already_ended_does_not_block(db):
    db.add(CalendarCache(user_id="u1", event_id="e2", title="Earlier",
                         starts_at=NOW - timedelta(hours=2), ends_at=NOW - timedelta(hours=1)))
    db.commit()
    assert service.gate_for_user(db, "u1", NOW).allowed


def test_recorded_prompt_starts_the_15_minute_gap(db):
    session = db.get(Session, "s1")
    service.record_intervention(db, session, "distracted", {"title": "t"}, 42.0, NOW)
    assert session.interventions_total == 1
    assert service.gate_for_user(db, "u1", NOW + timedelta(minutes=10)).reason == "too_soon"
    assert service.gate_for_user(db, "u1", NOW + timedelta(minutes=15)).allowed


def test_gap_applies_across_sessions(db):
    db.add(Session(id="s2", user_id="u1", start_time=NOW))
    db.commit()
    service.record_intervention(db, db.get(Session, "s1"), "stuck", {}, 30.0, NOW)
    # a brand-new session 5 minutes later still has to wait
    assert service.gate_for_user(db, "u1", NOW + timedelta(minutes=5)).reason == "too_soon"


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, "u1")
    return TestClient(app)


def test_pause_and_resume(client, db):
    r = client.post("/pause", json={"minutes": 30})
    assert r.status_code == 200 and r.json()["paused"] is True
    assert client.get("/pause").json()["paused"] is True
    assert service.gate_for_user(db, "u1", datetime.now(timezone.utc)).reason == "paused"

    assert client.delete("/pause").status_code == 204
    assert client.get("/pause").json()["paused"] is False


def test_pause_needs_minutes_or_end_of_day(client):
    assert client.post("/pause", json={}).status_code == 422


def test_settings_quiet_hours_and_timezone(client, db):
    r = client.put("/settings", json={"timezone": "Asia/Kolkata",
                                      "quiet_hours": {"start": "15:00", "end": "16:00"}})
    assert r.status_code == 200
    assert r.json()["timezone"] == "Asia/Kolkata"
    assert r.json()["quiet_hours"] == {"start": "15:00", "end": "16:00"}
    assert service.gate_for_user(db, "u1", NOW).reason == "quiet_hours"

    client.put("/settings", json={"quiet_hours": None})
    assert client.get("/settings").json()["quiet_hours"] is None


def test_settings_rejects_bad_values(client):
    assert client.put("/settings", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.put("/settings", json={"quiet_hours": {"start": "25:00", "end": "07:00"}}).status_code == 422
