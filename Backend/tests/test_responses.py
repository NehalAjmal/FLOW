# Task 2: answering prompts (respond / override / report) and the counts.
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
from auth.dependencies import get_current_user
from interventions import router as intervention_router_module
from interventions import service, threshold_hook

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id="u1", full_name="Me", email="me@example.com", password_hash="x"),
        User(id="u2", full_name="Someone Else", email="else@example.com", password_hash="x"),
        Session(id="s1", user_id="u1", start_time=NOW),
    ])
    db.commit()
    yield db
    db.close()


@pytest.fixture
def calls(monkeypatch):
    """Record what the router sends to the live screen and to the threshold."""
    seen = {"cleared": [], "threshold": []}
    monkeypatch.setattr(intervention_router_module, "_clear_live", lambda sid: seen["cleared"].append(sid))
    monkeypatch.setattr(threshold_hook, "_update",
                        lambda db, uid, resp: seen["threshold"].append(resp) or 0.65)
    return seen


@pytest.fixture
def client(db, calls):
    app = FastAPI()
    app.include_router(intervention_router_module.router, prefix="/intervention")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, "u1")
    return TestClient(app)


def make_prompt(db, kind="distracted", at=NOW):
    return service.record_intervention(db, db.get(Session, "s1"), kind, {"title": "t", "message": "m"}, 40.0, at)


def test_accept_is_counted_and_updates_threshold(client, db, calls):
    p = make_prompt(db)
    r = client.post(f"/intervention/{p.id}/respond", json={"response": "accepted"})
    assert r.status_code == 200
    assert r.json()["response"] == "accepted" and r.json()["threshold"] == 0.65
    assert db.get(Session, "s1").interventions_accepted == 1
    assert calls["threshold"] == ["accepted"]
    assert calls["cleared"] == ["s1"]


def test_dismiss_is_counted(client, db):
    p = make_prompt(db)
    client.post(f"/intervention/{p.id}/respond", json={"response": "dismissed"})
    counts = client.get("/intervention/session/s1/counts").json()
    assert counts["shown"] == 1 and counts["dismissed"] == 1 and counts["accepted"] == 0


def test_snooze_sets_time_and_blocks_until_then(client, db):
    p = make_prompt(db, at=datetime.now(timezone.utc))
    r = client.post(f"/intervention/{p.id}/respond", json={"response": "snoozed", "snooze_minutes": 5})
    assert r.json()["snooze_until"] is not None
    now = datetime.now(timezone.utc)
    assert service.gate_for_user(db, "u1", now).reason == "snoozed"
    # 6 minutes later the snooze is over, even though 15 minutes have not passed
    assert service.gate_for_user(db, "u1", now + timedelta(minutes=6)).allowed


def test_a_prompt_can_only_be_answered_once(client, db):
    p = make_prompt(db)
    client.post(f"/intervention/{p.id}/respond", json={"response": "dismissed"})
    r = client.post(f"/intervention/{p.id}/respond", json={"response": "accepted"})
    assert r.status_code == 409
    assert db.get(Session, "s1").interventions_accepted == 0


def test_override_with_reason(client, db, calls):
    p = make_prompt(db)
    r = client.post(f"/intervention/{p.id}/override", json={"reason": "deploy"})
    assert r.status_code == 200
    assert r.json()["response"] == "overridden" and r.json()["override_reason"] == "deploy"
    assert calls["threshold"] == ["overridden"]


def test_report_as_bad_with_reason(client, db, calls):
    p = make_prompt(db)
    client.post(f"/intervention/{p.id}/respond", json={"response": "dismissed"})
    # reporting still works after answering
    r = client.post(f"/intervention/{p.id}/report", json={"reason": "too_frequent", "free_text": "  twice in a row "})
    assert r.status_code == 200 and r.json()["report_reason"] == "too_frequent"
    assert db.get(type(p), p.id).report_text == "twice in a row"
    assert client.get("/intervention/session/s1/counts").json()["reported"] == 1
    assert calls["threshold"] == ["dismissed", "reported"]


def test_bad_values_are_rejected(client, db):
    p = make_prompt(db)
    assert client.post(f"/intervention/{p.id}/respond", json={"response": "maybe"}).status_code == 422
    assert client.post(f"/intervention/{p.id}/override", json={"reason": "bored"}).status_code == 422
    assert client.post(f"/intervention/{p.id}/report", json={"reason": "ugly"}).status_code == 422
    assert client.post(f"/intervention/{p.id}/respond",
                       json={"response": "snoozed", "snooze_minutes": 0}).status_code == 422


def test_cannot_touch_someone_elses_prompt(client, db):
    db.add(Session(id="s2", user_id="u2", start_time=NOW))
    db.commit()
    other = service.record_intervention(db, db.get(Session, "s2"), "stuck", {}, 30.0, NOW)
    assert client.get(f"/intervention/{other.id}").status_code == 404
    assert client.post(f"/intervention/{other.id}/respond", json={"response": "accepted"}).status_code == 404
    assert client.get("/intervention/session/s2/counts").status_code == 404


def test_answering_still_works_when_threshold_code_is_missing(client, db, monkeypatch):
    monkeypatch.setattr(threshold_hook, "_update", None)
    p = make_prompt(db)
    r = client.post(f"/intervention/{p.id}/respond", json={"response": "accepted"})
    assert r.status_code == 200 and r.json()["threshold"] is None
