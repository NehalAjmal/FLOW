# Task 4: full settings with consent enforcement, data summary/export, account delete.
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models  # noqa: registers every table
from db_models.base import Base, get_db
from db_models.breaks import Break
from db_models.data_export import DataExport
from db_models.intervention import Intervention
from db_models.rating import Rating
from db_models.session import Session
from db_models.user import User
from db_models.user_settings import UserSettings
from auth.dependencies import get_current_user
from consent.service import set_user_consent
from interventions import service as intervention_service
from migrations import add_settings_columns
from privacy import router as privacy_router_module
from settings_app.router import router as settings_router
from settings_app.service import feature_allowed

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id="u1", full_name="Me", email="me@example.com", password_hash="SECRET-HASH"),
        User(id="u2", full_name="Someone Else", email="else@example.com", password_hash="x"),
        Session(id="s1", user_id="u1", start_time=NOW, end_time=NOW, signal_log=[{"keystrokes": 3}]),
        Session(id="s2", user_id="u2", start_time=NOW, end_time=NOW),
    ])
    db.commit()
    yield db
    db.close()


@pytest.fixture
def stopped(monkeypatch):
    seen = []
    monkeypatch.setattr(privacy_router_module, "_stop_live_sessions", lambda db, uid: seen.append(uid))
    return seen


@pytest.fixture
def client(db, stopped):
    app = FastAPI()
    app.include_router(settings_router)
    app.include_router(privacy_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, "u1")
    return TestClient(app)


# ── settings ─────────────────────────────────────────────

def test_default_settings_shape(client):
    s = client.get("/settings").json()
    assert s["delivery_mode"] == "advisory" and s["break_length_sec"] == 300
    assert s["snooze_options"] == [5, 10, 15] and s["quiet_hours"] is None
    # no consent yet, so the switches report off
    assert s["camera_enabled"] is False and s["llm_enabled"] is False and s["calendar_enabled"] is False


def test_put_is_partial_and_returns_everything(client):
    r = client.put("/settings", json={"delivery_mode": "explained", "snooze_options": [15, 5, 5]})
    assert r.status_code == 200
    body = r.json()
    assert body["delivery_mode"] == "explained" and body["snooze_options"] == [5, 15]
    assert body["break_length_sec"] == 300          # untouched


def test_switch_cannot_go_on_without_consent(client, db):
    r = client.put("/settings", json={"camera_enabled": True})
    assert r.status_code == 403 and r.json()["detail"] == "camera_consent_required"
    set_user_consent(db, "u1", "camera", True)
    assert client.put("/settings", json={"camera_enabled": True}).json()["camera_enabled"] is True


def test_switch_off_overrides_consent(client, db):
    set_user_consent(db, "u1", "llm", True)
    assert feature_allowed(db, "u1", "llm")
    client.put("/settings", json={"llm_enabled": False})
    assert not feature_allowed(db, "u1", "llm")           # consent kept, feature off
    assert client.get("/settings").json()["llm_enabled"] is False


def test_bad_settings_rejected(client):
    assert client.put("/settings", json={"delivery_mode": "shout"}).status_code == 422
    assert client.put("/settings", json={"break_length_sec": 5}).status_code == 422
    assert client.put("/settings", json={"snooze_options": [0]}).status_code == 422
    assert client.put("/settings", json={"snooze_options": [1, 2, 3, 4, 5, 6]}).status_code == 422


# ── data summary + export ────────────────────────────────

def _add_my_data(db):
    p = intervention_service.record_intervention(db, db.get(Session, "s1"), "stuck", {}, 30.0, NOW)
    db.add(Break(session_id="s1", taken=True, taken_at=NOW, intervention_id=p.id))
    db.add(Rating(user_id="u1", session_id="s1", kind="focus", value=4, created_at=NOW))
    db.commit()


def test_data_summary_counts_only_my_data(client, db):
    _add_my_data(db)
    cats = {c["name"]: c for c in client.get("/me/data-summary").json()["categories"]}
    assert cats["sessions"]["item_count"] == 1 and cats["prompts"]["item_count"] == 1
    assert cats["breaks"]["item_count"] == 1 and cats["ratings"]["item_count"] == 1
    assert cats["sessions"]["retention_days"] is None     # no policy invented


def test_export_contains_my_data_and_no_secrets(client, db):
    _add_my_data(db)
    r = client.post("/me/data-export").json()
    assert r["status"] == "ready" and r["download_url"]
    assert client.get(f"/me/data-export/{r['id']}").json()["status"] == "ready"

    d = client.get(r["download_url"])
    assert d.status_code == 200 and "attachment" in d.headers["content-disposition"]
    data = d.json()
    assert data["profile"][0]["email"] == "me@example.com"
    assert "password_hash" not in data["profile"][0]
    assert "SECRET-HASH" not in d.text
    assert [s["id"] for s in data["sessions"]] == ["s1"]         # not u2's session
    assert len(data["prompts"]) == 1 and len(data["breaks"]) == 1


def test_cannot_read_someone_elses_export(client, db):
    other = DataExport(user_id="u2", status="ready", created_at=NOW, payload={})
    db.add(other)
    db.commit()
    assert client.get(f"/me/data-export/{other.id}").status_code == 404
    assert client.get(f"/me/data-export/{other.id}/download").status_code == 404


# ── delete account ───────────────────────────────────────

def test_delete_me_removes_everything_of_mine_only(client, db, stopped):
    _add_my_data(db)
    intervention_service.get_settings(db, "u1")
    set_user_consent(db, "u1", "camera", True)
    client.post("/me/data-export")

    assert client.delete("/me").status_code == 204
    assert stopped == ["u1"]
    db.expire_all()
    assert db.get(User, "u1") is None
    for model in (Session, Intervention, Rating, DataExport, UserSettings, Break):
        rows = db.query(model).all()
        assert all(getattr(r, "user_id", "u2") != "u1" for r in rows), model
    assert db.query(Break).count() == 0
    # the other user is untouched
    assert db.get(User, "u2") is not None and db.get(Session, "s2") is not None


# ── migration ────────────────────────────────────────────

def test_settings_migration_adds_columns_once():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE user_settings (user_id VARCHAR(36) PRIMARY KEY)"))
    assert len(add_settings_columns.run(engine)) == 6
    assert add_settings_columns.run(engine) == []
