from datetime import datetime, timezone

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models

from db_models.base import Base, get_db
from db_models.user import User
from db_models.session import Session
from db_models.intervention import Intervention

from auth.dependencies import get_current_user

from engine.decision import DecisionEngine
from engine.explainer import build_explanation
from engine.threshold import update_threshold

from interventions import service
from interventions import router as router_module


NOW = datetime.now(timezone.utc)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine)
    database = factory()

    database.add_all([
        User(
            id="u1",
            full_name="First User",
            email="first@example.com",
            password_hash="x",
        ),
        User(
            id="u2",
            full_name="Second User",
            email="second@example.com",
            password_hash="x",
        ),
    ])

    database.commit()

    database.add_all([
        Session(
            id="s1",
            user_id="u1",
            start_time=NOW,
        ),
        Session(
            id="s2",
            user_id="u2",
            start_time=NOW,
        ),
    ])

    database.commit()

    yield database

    database.close()
    engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    app = FastAPI()

    app.include_router(
        router_module.router,
        prefix="/intervention",
    )

    app.include_router(
        router_module.router,
        prefix="/api/v1/intervention",
    )

    app.dependency_overrides[get_db] = lambda: db

    app.dependency_overrides[get_current_user] = (
        lambda: db.get(User, "u1")
    )

    monkeypatch.setattr(
        router_module,
        "_clear_live",
        lambda session_id: None,
    )

    with TestClient(app) as test_client:
        yield test_client


def make_explanation():
    decision = DecisionEngine().compute(
        deviation=0.70,
        fatigue=0.60,
        ultradian=0.40,
        biometric=0.80,
    )

    return build_explanation(
        decision=decision,
        state=decision["state"],
        focus_score=decision["focus_score"],
        adaptive_threshold=0.65,
        trough_pressure=0.0,
        trigger="sustained_low_focus",
        minutes_in_state=6.0,
    )


def make_prompt(
    db,
    session_id="s1",
    with_explanation=True,
):
    return service.record_intervention(
        db=db,
        session=db.get(Session, session_id),
        kind="distracted",
        payload={
            "title": "Take a break",
            "message": "Focus has decreased.",
            "action_label": "Take Break",
        },
        focus_score=44.0,
        now=NOW,
        explanation=(
            make_explanation()
            if with_explanation
            else None
        ),
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "/intervention",
        "/api/v1/intervention",
    ],
)
def test_get_explanation(client, db, prefix):
    prompt = make_prompt(db)

    response = client.get(
        f"{prefix}/{prompt.id}/explain"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["intervention_id"] == prompt.id
    assert data["decision_source"] == "weighted_fusion"
    assert data["focus_score"] == pytest.approx(0.44)
    assert data["adaptive_threshold"] == 0.65
    assert data["below_threshold"] is True
    assert len(data["signals"]) == 4


def test_explanation_persisted(db):
    prompt = make_prompt(db)

    prompt_id = prompt.id
    expected = make_explanation()

    factory = sessionmaker(bind=db.get_bind())

    with factory() as new_db:
        stored = new_db.get(
            Intervention,
            prompt_id,
        )

        assert stored.explanation == expected


def test_other_user_explanation_is_private(client, db):
    prompt = make_prompt(
        db,
        session_id="s2",
    )

    response = client.get(
        f"/intervention/{prompt.id}/explain"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Intervention not found"
    )


def test_unknown_intervention(client):
    response = client.get(
        "/intervention/unknown-id/explain"
    )

    assert response.status_code == 404


def test_legacy_intervention_without_explanation(client, db):
    prompt = make_prompt(
        db,
        with_explanation=False,
    )

    response = client.get(
        f"/intervention/{prompt.id}/explain"
    )

    assert response.status_code == 404

    assert response.json()["detail"] == (
        "Explanation not available"
    )


def test_threshold_change_does_not_rewrite_snapshot(
    client,
    db,
):
    prompt = make_prompt(db)

    before = client.get(
        f"/intervention/{prompt.id}/explain"
    ).json()

    new_threshold = update_threshold(
        db,
        "u1",
        "accepted",
    )

    assert new_threshold == pytest.approx(0.67)

    after = client.get(
        f"/intervention/{prompt.id}/explain"
    ).json()

    assert before == after
    assert after["adaptive_threshold"] == 0.65


def test_response_does_not_rewrite_snapshot(client, db):
    prompt = make_prompt(db)

    url = f"/intervention/{prompt.id}"

    before = client.get(
        f"{url}/explain"
    ).json()

    response = client.post(
        f"{url}/respond",
        json={"response": "accepted"},
    )

    assert response.status_code == 200
    assert response.json()["threshold"] == pytest.approx(
        0.67
    )

    after = client.get(
        f"{url}/explain"
    ).json()

    assert before == after


def test_unauthenticated_request_is_rejected():
    app = FastAPI()

    app.include_router(
        router_module.router,
        prefix="/intervention",
    )

    with TestClient(app) as anonymous:
        response = anonymous.get(
            "/intervention/unknown-id/explain"
        )

    assert response.status_code in (401, 403)
