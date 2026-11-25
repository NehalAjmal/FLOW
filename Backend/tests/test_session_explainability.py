from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models

from db_models.base import Base
from db_models.user import User
from db_models.session import Session
from db_models.intervention import Intervention

from sessions import service
from interventions import service as intervention_service

from engine.threshold import get_threshold, update_threshold


NOW = datetime(
    2026, 11, 25, 10, 0,
    tzinfo=timezone.utc,
)

USER_ID = "test-user"
SESSION_ID = "test-session"

PROMPT = {
    "title": "Take a break",
    "message": "Consider taking a short break.",
    "action_label": "Take Break",
}


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine)
    database = factory()

    database.add(
        User(
            id=USER_ID,
            full_name="Integration Test User",
            email="integration@example.com",
            password_hash="x",
            pattern_model={
                "schema_version": "learning_v3",
                "parameters": {
                    "adaptive_threshold": 0.65,
                    "ultradian_cycle_minutes": 90,
                    "trough_minute": 45,
                },
            },
        )
    )

    database.commit()

    database.add(
        Session(
            id=SESSION_ID,
            user_id=USER_ID,
            task_description="Integration testing",
            declared_difficulty="moderate",
            planned_duration_min=90,
            start_time=NOW - timedelta(minutes=10),
            signal_log=[],
        )
    )

    database.commit()

    # Isolate process-local session state.
    monkeypatch.setattr(
        service,
        "_live_sessions",
        {},
    )

    # Freeze the server clock.
    monkeypatch.setattr(
        service,
        "_utcnow",
        lambda: NOW,
    )

    # No physical camera or heart-rate device.
    monkeypatch.setattr(
        service.fatigue_service,
        "get_state",
        lambda: {},
    )

    monkeypatch.setattr(
        service,
        "_latest_hr_hrv",
        lambda *args: None,
    )

    # Avoid external LLM or cached message dependencies.
    monkeypatch.setattr(
        service,
        "get_intervention",
        lambda state: dict(PROMPT),
    )

    try:
        yield database
    finally:
        database.close()
        engine.dispose()


def prepare_live(
    db,
    monkeypatch,
    *,
    state="distracted",
    minutes_in_state=6.0,
    elapsed_minutes=10,
    deviation=0.70,
    fatigue=0.60,
    ultradian=0.40,
    biometric=0.80,
):
    session = db.get(Session, SESSION_ID)

    live = service._rehydrate_live(
        db,
        session,
    )

    live["state"] = state
    live["minutes_in_state"] = minutes_in_state

    live["session_start"] = (
        NOW - timedelta(minutes=elapsed_minutes)
    )

    live["intervention"] = None

    engines = live["engines"]

    monkeypatch.setattr(
        engines["deviation"],
        "compute",
        lambda **kwargs: deviation,
    )

    monkeypatch.setattr(
        engines["ultradian"],
        "compute",
        lambda: ultradian,
    )

    monkeypatch.setattr(
        service.fatigue_service,
        "get_state",
        lambda: {"fatigue_score": fatigue},
    )

    monkeypatch.setattr(
        service,
        "_latest_hr_hrv",
        lambda *args: (
            (70.0, 50.0)
            if biometric is not None
            else None
        ),
    )

    monkeypatch.setattr(
        engines["biometric"],
        "compute",
        lambda **kwargs: biometric,
    )

    return live


def ingest(
    db,
    *,
    keystrokes=10,
    switches=2,
    idle=5,
    window="Visual Studio Code",
):
    return service.ingest_signal(
        db=db,
        session_id=SESSION_ID,
        keystroke_count=keystrokes,
        window_switches=switches,
        idle_seconds=idle,
        mouse_distance_px=100,
        active_window=window,
        timestamp=NOW.isoformat(),
    )


def stored_prompts(db):
    return (
        db.query(Intervention)
        .filter(
            Intervention.session_id == SESSION_ID
        )
        .all()
    )


# 1. Full session-to-database explanation pipeline.

def test_ingest_persists_explanation(
    db,
    monkeypatch,
):
    prepare_live(db, monkeypatch)

    live = ingest(db)

    assert live["state"] == "distracted"
    assert live["focus_score"] == pytest.approx(44.0)

    assert live["intervention"] is not None

    rows = stored_prompts(db)

    assert len(rows) == 1

    row = rows[0]

    assert row.id == live["intervention"]["id"]
    assert row.user_id == USER_ID
    assert row.kind == "distracted"
    assert row.focus_score == pytest.approx(44.0)

    explanation = row.explanation

    assert explanation is not None

    assert explanation["decision_source"] == (
        "weighted_fusion"
    )

    assert explanation["trigger"] == (
        "sustained_low_focus"
    )

    assert explanation["focus_score"] == (
        pytest.approx(0.44)
    )

    assert explanation["adaptive_threshold"] == (
        pytest.approx(0.65)
    )

    assert explanation["below_threshold"] is True

    assert explanation["minutes_in_state"] == (
        pytest.approx(6.5)
    )

    assert explanation["weighted_score"] == (
        pytest.approx(0.44)
    )

    assert explanation["trough_penalty"] == 0.0

    assert sum(
        signal["weight"]
        for signal in explanation["signals"].values()
    ) == pytest.approx(1.0)

    assert db.get(
        Session,
        SESSION_ID,
    ).interventions_total == 1


# 2. Predictive trough can trigger above the threshold.

def test_predicted_trough_explanation(
    db,
    monkeypatch,
):
    prepare_live(
        db,
        monkeypatch,
        state="deep_work",
        minutes_in_state=0,
        elapsed_minutes=44,
        deviation=0.0,
        fatigue=0.0,
        ultradian=0.0,
        biometric=1.0,
    )

    live = ingest(db)

    assert live["focus_score"] == pytest.approx(82.0)
    assert live["intervention"]["kind"] == "trough"

    rows = stored_prompts(db)

    assert len(rows) == 1

    explanation = rows[0].explanation

    assert explanation["trigger"] == (
        "predicted_trough"
    )

    assert explanation["below_threshold"] is False

    assert explanation["trough_pressure"] == (
        pytest.approx(0.9)
    )

    assert explanation["trough_penalty"] == (
        pytest.approx(0.18)
    )

    assert explanation["focus_score"] == (
        pytest.approx(0.82)
    )


# 3. Gating must prevent database insertion.

def test_paused_user_gets_no_intervention(
    db,
    monkeypatch,
):
    prepare_live(db, monkeypatch)

    settings = intervention_service.get_settings(
        db,
        USER_ID,
    )

    settings.paused_until = (
        NOW + timedelta(minutes=30)
    )

    db.commit()

    live = ingest(db)

    assert live["intervention"] is None
    assert live["gate_reason"] == "paused"

    assert stored_prompts(db) == []

    assert db.get(
        Session,
        SESSION_ID,
    ).interventions_total == 0


# 4. Fallback explanations must not invent contributions.

def test_fallback_explanation(
    db,
    monkeypatch,
):
    live = prepare_live(
        db,
        monkeypatch,
        state="stuck",
    )

    def fail_decision(**kwargs):
        raise RuntimeError(
            "Simulated decision engine failure"
        )

    monkeypatch.setattr(
        live["engines"]["decision"],
        "compute",
        fail_decision,
    )

    result = ingest(
        db,
        keystrokes=2,
        switches=1,
        idle=10,
    )

    assert result["state"] == "stuck"
    assert result["focus_score"] == 35.0

    rows = stored_prompts(db)

    assert len(rows) == 1

    explanation = rows[0].explanation

    assert explanation["decision_source"] == (
        "fallback"
    )

    assert explanation["focus_score"] == (
        pytest.approx(0.35)
    )

    assert explanation["weighted_score"] is None
    assert explanation["trough_penalty"] is None

    for signal in explanation["signals"].values():
        assert signal["available"] is False
        assert signal["contribution"] is None
        assert signal["weight"] is None


# 5. Threshold changes must affect actual prompt eligibility.

def test_adaptive_threshold_changes_prompt(
    db,
    monkeypatch,
):
    user = db.get(User, USER_ID)

    user.pattern_model = {
        "schema_version": "learning_v3",
        "parameters": {
            "adaptive_threshold": 0.55,
            "trough_minute": 45,
            "ultradian_cycle_minutes": 90,
        },
    }

    db.commit()

    prepare_live(
        db,
        monkeypatch,
        state="fatigue",
        deviation=0.30,
        fatigue=0.80,
        ultradian=0.20,
        biometric=1.0,
    )

    before = ingest(db)

    # Weighted score:
    # 0.40*0.70 + 0.30*0.20
    # + 0.20*0.80 + 0.10*1.00 = 0.60

    assert before["state"] == "fatigue"

    assert before["focus_score"] == (
        pytest.approx(60.0)
    )

    assert get_threshold(db, USER_ID) == (
        pytest.approx(0.55)
    )

    assert before["intervention"] is None
    assert stored_prompts(db) == []

    # Simulate three previously accepted responses.
    for _ in range(3):
        update_threshold(
            db,
            USER_ID,
            "accepted",
        )

    assert get_threshold(db, USER_ID) == (
        pytest.approx(0.61)
    )

    # Identical signal inputs, higher personalized threshold.
    after = ingest(db)

    assert after["state"] == "fatigue"

    assert after["focus_score"] == (
        pytest.approx(60.0)
    )

    assert after["intervention"] is not None

    rows = stored_prompts(db)

    assert len(rows) == 1

    explanation = rows[0].explanation

    assert explanation["adaptive_threshold"] == (
        pytest.approx(0.61)
    )

    assert explanation["focus_score"] == (
        pytest.approx(0.60)
    )

    assert explanation["below_threshold"] is True


# 6. Deep work is protected from ordinary prompts.

def test_deep_work_remains_protected(
    db,
    monkeypatch,
):
    user = db.get(User, USER_ID)

    user.pattern_model = {
        "parameters": {
            "adaptive_threshold": 0.80,
        },
    }

    db.commit()

    prepare_live(
        db,
        monkeypatch,
        state="deep_work",
        deviation=0.30,
        fatigue=0.30,
        ultradian=0.20,
        biometric=1.0,
    )

    live = ingest(db)

    assert live["state"] == "deep_work"

    assert live["focus_score"] == (
        pytest.approx(75.0)
    )

    assert live["intervention"] is None
    assert stored_prompts(db) == []


# 7. Preserve the existing neutral-state policy.

def test_neutral_state_remains_protected(
    db,
    monkeypatch,
):
    prepare_live(
        db,
        monkeypatch,
        state="neutral",
        deviation=0.40,
        fatigue=0.40,
        ultradian=0.40,
        biometric=0.60,
    )

    live = ingest(db)

    assert live["state"] == "neutral"

    assert live["focus_score"] == (
        pytest.approx(60.0)
    )

    assert get_threshold(db, USER_ID) == (
        pytest.approx(0.65)
    )

    assert live["intervention"] is None
    assert stored_prompts(db) == []


# 8. Repeated ticks must not duplicate a live prompt.

def test_repeated_ticks_do_not_duplicate_prompt(
    db,
    monkeypatch,
):
    prepare_live(db, monkeypatch)

    first = ingest(db)

    assert first["intervention"] is not None

    first_id = first["intervention"]["id"]

    for _ in range(5):
        result = ingest(db)

        assert result["intervention"]["id"] == first_id

    assert len(stored_prompts(db)) == 1

    assert db.get(
        Session,
        SESSION_ID,
    ).interventions_total == 1


# 9. Explanations must survive a new database session.

def test_ingested_explanation_survives_reload(
    db,
    monkeypatch,
):
    prepare_live(db, monkeypatch)

    live = ingest(db)

    intervention_id = live["intervention"]["id"]

    original = db.get(
        Intervention,
        intervention_id,
    ).explanation

    factory = sessionmaker(bind=db.get_bind())

    with factory() as new_db:
        row = new_db.get(
            Intervention,
            intervention_id,
        )

        assert row is not None
        assert row.explanation == original

        assert row.explanation["focus_score"] == (
            pytest.approx(0.44)
        )


# 10. Respect the minimum state duration.

def test_short_state_does_not_trigger_prompt(
    db,
    monkeypatch,
):
    prepare_live(
        db,
        monkeypatch,
        minutes_in_state=4.5,
    )

    live = ingest(db)

    assert live["minutes_in_state"] == 5.0
    assert live["intervention"] is None
    assert stored_prompts(db) == []

def test_status_returns_latest_threshold(
    db,
    monkeypatch,
):
    prepare_live(db, monkeypatch)

    before = service.get_session_status(
        db,
        SESSION_ID,
    )

    assert before["adaptive_threshold"] == (
        pytest.approx(0.65)
    )

    update_threshold(
        db,
        USER_ID,
        "accepted",
    )

    # No signal ingestion between update and status.
    after = service.get_session_status(
        db,
        SESSION_ID,
    )

    assert after["adaptive_threshold"] == (
        pytest.approx(0.67)
    )


def test_status_threshold_without_live_session(db):
    update_threshold(
        db,
        USER_ID,
        "accepted",
    )

    assert SESSION_ID not in service._live_sessions

    status = service.get_session_status(
        db,
        SESSION_ID,
    )

    assert status["adaptive_threshold"] == (
        pytest.approx(0.67)
    )
