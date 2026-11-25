
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models

from db_models.base import Base
from db_models.user import User
from db_models.session import Session
from db_models.biometric import BiometricReading

from sessions import service
from sessions.schemas import CameraMetrics

from biometric import router as biometric_router
from biometric.schemas import BiometricIngestRequest


NOW = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)

USER_A = "sensor-user-a"
USER_B = "sensor-user-b"

SESSION_A = "sensor-session-a"
SESSION_B = "sensor-session-b"


@pytest.fixture
def environment(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine)
    db = factory()

    users = {}

    for user_id, email in [
        (USER_A, "sensor-a@example.com"),
        (USER_B, "sensor-b@example.com"),
    ]:
        user = User(
            id=user_id,
            full_name=user_id,
            email=email,
            password_hash="test-only",
        )
        db.add(user)
        users[user_id] = user

    db.commit()

    for session_id, user_id in [
        (SESSION_A, USER_A),
        (SESSION_B, USER_B),
    ]:
        db.add(
            Session(
                id=session_id,
                user_id=user_id,
                task_description="Sensor isolation test",
                declared_difficulty="moderate",
                planned_duration_min=90,
                start_time=NOW - timedelta(minutes=10),
                signal_log=[],
            )
        )

    db.commit()

    permissions = {
        USER_A: True,
        USER_B: True,
    }

    clock = {"now": NOW}

    def feature_allowed(db, user_id, feature):
        return permissions.get(user_id, False)

    monkeypatch.setattr(service, "_live_sessions", {})
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])

    monkeypatch.setattr(
        service,
        "feature_allowed",
        feature_allowed,
    )

    monkeypatch.setattr(
        biometric_router,
        "feature_allowed",
        feature_allowed,
    )

    monkeypatch.setattr(
        service,
        "get_intervention",
        lambda state: {
            "title": "Test intervention",
            "message": "Test message",
            "action_label": "Take Break",
        },
    )

    try:
        yield db, users, permissions, clock
    finally:
        db.close()
        engine.dispose()


def send_signal(db, session_id, camera=None):
    return service.ingest_signal(
        db=db,
        session_id=session_id,
        keystroke_count=30,
        window_switches=1,
        idle_seconds=2,
        mouse_distance_px=100,
        active_window="development",
        timestamp=NOW.isoformat(),
        camera=camera,
    )


def get_camera(db, session_id):
    session = db.get(Session, session_id)
    return service.current_camera(db, session)


# ---------------------------------------------------------
# CAMERA SCHEMA VALIDATION
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "field,value",
    [
        ("fatigue_score", -0.1),
        ("fatigue_score", 1.1),
        ("fatigue_score", float("nan")),
        ("fatigue_score", float("inf")),
        ("fatigue_score", float("-inf")),
        ("ear", -0.1),
        ("ear", 1.1),
        ("ear", float("nan")),
        ("heart_rate_bpm", 0),
        ("heart_rate_bpm", 251),
        ("heart_rate_bpm", float("inf")),
        ("hr_confidence", -0.1),
        ("hr_confidence", 1.1),
        ("hr_confidence", float("nan")),
    ],
)
def test_invalid_camera_measurements_rejected(field, value):
    with pytest.raises(ValidationError):
        CameraMetrics(**{field: value})


def test_valid_camera_measurements():
    camera = CameraMetrics(
        fatigue_score=0.42,
        ear=0.28,
        heart_rate_bpm=76.0,
        hr_confidence=0.81,
    )

    assert camera.fatigue_score == 0.42
    assert camera.ear == 0.28
    assert camera.heart_rate_bpm == 76.0
    assert camera.hr_confidence == 0.81


def test_missing_camera_measurements_are_none():
    camera = CameraMetrics()

    assert camera.fatigue_score is None
    assert camera.ear is None
    assert camera.heart_rate_bpm is None
    assert camera.hr_confidence is None


def test_zero_fatigue_is_valid_measurement():
    camera = CameraMetrics(fatigue_score=0.0)
    assert camera.fatigue_score == 0.0


# ---------------------------------------------------------
# SESSION ISOLATION
# ---------------------------------------------------------

def test_camera_data_isolated_between_users(environment):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.85, ear=0.12),
    )

    send_signal(
        db,
        SESSION_B,
        CameraMetrics(fatigue_score=0.15, ear=0.32),
    )

    camera_a = get_camera(db, SESSION_A)
    camera_b = get_camera(db, SESSION_B)

    assert camera_a["fatigue_score"] == 0.85
    assert camera_b["fatigue_score"] == 0.15

    assert camera_a["ear"] == 0.12
    assert camera_b["ear"] == 0.32


def test_camera_data_not_shared_with_camera_off_session(
    environment,
):
    db, users, permissions, clock = environment

    permissions[USER_B] = False

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.9, ear=0.1),
    )

    send_signal(db, SESSION_B)

    assert get_camera(db, SESSION_A)["fatigue_score"] == 0.9
    assert get_camera(db, SESSION_B) == {}


# ---------------------------------------------------------
# CAMERA PERMISSION
# ---------------------------------------------------------

def test_camera_data_discarded_without_permission(environment):
    db, users, permissions, clock = environment

    permissions[USER_A] = False

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.8, ear=0.2),
    )

    assert get_camera(db, SESSION_A) == {}

    session = db.get(Session, SESSION_A)

    assert session.signal_log[-1]["fatigue"] is None


def test_camera_permission_withdrawal_clears_data(environment):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.7),
    )

    assert get_camera(db, SESSION_A)["fatigue_score"] == 0.7

    permissions[USER_A] = False

    assert get_camera(db, SESSION_A) == {}

    # Re-enabling must not restore the old measurement.
    permissions[USER_A] = True

    assert get_camera(db, SESSION_A) == {}


def test_camera_permission_withdrawal_does_not_affect_other_user(
    environment,
):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.7),
    )

    send_signal(
        db,
        SESSION_B,
        CameraMetrics(fatigue_score=0.2),
    )

    permissions[USER_A] = False

    assert get_camera(db, SESSION_A) == {}
    assert get_camera(db, SESSION_B)["fatigue_score"] == 0.2


# ---------------------------------------------------------
# FRESHNESS AND SESSION LIFECYCLE
# ---------------------------------------------------------

def test_camera_measurement_expires(environment):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.6),
    )

    clock["now"] = NOW + timedelta(seconds=61)

    assert get_camera(db, SESSION_A) == {}


def test_fresh_camera_measurement_available(environment):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.6),
    )

    clock["now"] = NOW + timedelta(seconds=30)

    assert get_camera(db, SESSION_A)["fatigue_score"] == 0.6


def test_missing_camera_tick_clears_previous_measurement(
    environment,
):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.8),
    )

    clock["now"] = NOW + timedelta(seconds=30)

    send_signal(db, SESSION_A, camera=None)

    assert get_camera(db, SESSION_A) == {}

    session = db.get(Session, SESSION_A)

    assert session.signal_log[-1]["fatigue"] is None


def test_ended_session_has_no_live_camera(environment):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.7),
    )

    session = db.get(Session, SESSION_A)
    session.end_time = NOW
    db.commit()

    assert get_camera(db, SESSION_A) == {}

    assert send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.9),
    ) is None


# ---------------------------------------------------------
# BIOMETRIC OWNERSHIP
# ---------------------------------------------------------

def test_foreign_biometric_ingestion_rejected(environment):
    db, users, permissions, clock = environment

    payload = BiometricIngestRequest(
        session_id=SESSION_B,
        heart_rate_bpm=75.0,
        hrv_sdnn=50.0,
        source="apple_watch",
    )

    with pytest.raises(HTTPException) as error:
        biometric_router.ingest_biometric(
            payload=payload,
            db=db,
            current_user=users[USER_A],
        )

    assert error.value.status_code == 403

    assert db.query(BiometricReading).count() == 0


def test_foreign_biometric_retrieval_rejected(environment):
    db, users, permissions, clock = environment

    with pytest.raises(HTTPException) as error:
        biometric_router.get_latest_biometric(
            session_id=SESSION_B,
            db=db,
            current_user=users[USER_A],
        )

    assert error.value.status_code == 403


def test_unknown_biometric_session_rejected(environment):
    db, users, permissions, clock = environment

    payload = BiometricIngestRequest(
        session_id="nonexistent-session",
        heart_rate_bpm=75.0,
        source="apple_watch",
    )

    with pytest.raises(HTTPException) as error:
        biometric_router.ingest_biometric(
            payload=payload,
            db=db,
            current_user=users[USER_A],
        )

    assert error.value.status_code == 404


def test_biometric_camera_consent_required(environment):
    db, users, permissions, clock = environment

    permissions[USER_A] = False

    payload = BiometricIngestRequest(
        session_id=SESSION_A,
        ear_value=0.25,
        source="webcam",
    )

    with pytest.raises(HTTPException) as error:
        biometric_router.ingest_biometric(
            payload=payload,
            db=db,
            current_user=users[USER_A],
        )

    assert error.value.status_code == 403
    assert db.query(BiometricReading).count() == 0


def test_biometric_camera_fallback_is_session_specific(
    environment,
):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(
            fatigue_score=0.75,
            ear=0.15,
            heart_rate_bpm=78.0,
            hr_confidence=0.8,
        ),
    )

    result_a = biometric_router.get_latest_biometric(
        session_id=SESSION_A,
        db=db,
        current_user=users[USER_A],
    )

    result_b = biometric_router.get_latest_biometric(
        session_id=SESSION_B,
        db=db,
        current_user=users[USER_B],
    )

    assert result_a.has_data is True
    assert result_a.fatigue_signal == 0.75
    assert result_a.ear_value == 0.15

    assert result_b.has_data is False
    assert result_b.fatigue_signal is None
    assert result_b.ear_value is None


def test_biometric_fallback_hidden_after_permission_withdrawal(
    environment,
):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.8, ear=0.15),
    )

    permissions[USER_A] = False

    result = biometric_router.get_latest_biometric(
        session_id=SESSION_A,
        db=db,
        current_user=users[USER_A],
    )

    assert result.has_data is False
    assert result.fatigue_signal is None
    assert result.ear_value is None


def test_no_biometric_data_returns_none(environment):
    db, users, permissions, clock = environment

    result = biometric_router.get_latest_biometric(
        session_id=SESSION_A,
        db=db,
        current_user=users[USER_A],
    )

    assert result.has_data is False
    assert result.heart_rate_bpm is None
    assert result.hrv_sdnn is None
    assert result.ear_value is None
    assert result.fatigue_signal is None


# ---------------------------------------------------------
# ML REGRESSION
# ---------------------------------------------------------

def test_focus_scoring_works_without_camera(environment):
    db, users, permissions, clock = environment

    permissions[USER_A] = False

    result = send_signal(db, SESSION_A)

    assert result is not None

    session = db.get(Session, SESSION_A)
    latest = session.signal_log[-1]

    assert latest["fatigue"] is None
    assert latest["score"] is not None
    assert 0 <= latest["score"] <= 100


def test_real_zero_fatigue_preserved_in_log(environment):
    db, users, permissions, clock = environment

    send_signal(
        db,
        SESSION_A,
        CameraMetrics(fatigue_score=0.0),
    )

    session = db.get(Session, SESSION_A)

    assert session.signal_log[-1]["fatigue"] == 0.0
