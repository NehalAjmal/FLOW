# Task 7: no demo team, no fixed meeting window, no made-up values.
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models  # noqa: registers every table
from db_models.base import Base
from db_models.session import Session
from db_models.team import Team
from db_models.user import User
from auth.utils import verify_password
from consent.service import set_user_consent

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def test_demo_seed_scripts_are_gone():
    for f in ["seed_db.py", "demo/seed_data.py", "demo/demo_responses.json"]:
        assert not (BACKEND / f).exists(), f
    setup = (BACKEND / "setup.py").read_text(encoding="utf-8")
    assert "seed_demo_team" not in setup and "ERR011" not in setup and "000000" not in setup


def test_create_team(db):
    from create_team import create_team
    team, key = create_team(db, "Real Team")
    assert len(team.company_code) == 6 and team.company_code.isalnum()
    assert len(key) == 6 and key.isdigit()
    assert team.admin_key != key and verify_password(key, team.admin_key)   # only the hash is stored
    other, _ = create_team(db, "Another")
    assert other.company_code != team.company_code


def test_admin_dashboard_has_no_fixed_window(db):
    from admin.service import get_admin_dashboard
    db.add(Team(id="t1", name="T", company_code="T00001", admin_key="x"))
    for i in range(5):
        db.add(User(id=f"m{i}", full_name=f"M{i}", email=f"m{i}@example.com", password_hash="x",
                    role="employee", team_id="t1"))
    db.commit()
    for i in range(5):
        set_user_consent(db, f"m{i}", "team_aggregate", True)

    out = get_admin_dashboard(db, "t1")
    assert out.best_meeting_window == "--:--"          # not enough data: say so, don't invent 14:00
    assert out.state_distribution == {}                # nobody is in a session

    now = datetime.now(timezone.utc)
    db.add(Session(id="live", user_id="m0", start_time=now - timedelta(minutes=5),
                   signal_log=[{"state": "stuck", "score": 40}]))
    db.commit()
    assert get_admin_dashboard(db, "t1").state_distribution == {"stuck": 1}


def test_session_status_without_live_state(db, monkeypatch):
    stub = types.ModuleType("ml_models.fatigue_model")
    stub.fatigue_service = types.SimpleNamespace(get_state=lambda: {}, start=lambda: None, stop=lambda: None)
    monkeypatch.setitem(sys.modules, "ml_models.fatigue_model", stub)
    from sessions import service

    db.add(User(id="u1", full_name="U", email="u@example.com", password_hash="x"))
    db.add(Session(id="s1", user_id="u1", start_time=datetime.now(timezone.utc), signal_log=[]))
    db.commit()
    st = service.get_session_status(db, "s1")
    assert st["state"] is None and st["focus_score"] is None     # was "deep_work" and 0.0
    assert st["signals"]["ultradian"] is None                    # was a made-up 0.5
    assert st["signals"]["behavioral"] is None


def test_focus_dna_prompt_without_data():
    from llm.prompts import focus_dna_insight_prompt
    p = focus_dna_insight_prompt("U", [], None, 0.0, "—", 0, 0.0)
    assert "not enough data yet" in p and "not learned yet" in p and "/ 5.0" not in p
