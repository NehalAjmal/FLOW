# tests/test_threshold_persistence.py

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db_models.user import User
from engine.threshold import get_threshold, update_threshold


@pytest.fixture
def db_factory():
    engine = create_engine("sqlite:///:memory:")

    User.__table__.create(bind=engine)

    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        db.add_all([
            User(
                id="user-1",
                full_name="Test User One",
                email="user1@example.com",
                password_hash="test",
                pattern_model={
                    "schema_version": "learning_v3",
                    "parameters": {
                        "ultradian_cycle_minutes": 90,
                        "trough_minute": 45,
                    },
                },
            ),
            User(
                id="user-2",
                full_name="Test User Two",
                email="user2@example.com",
                password_hash="test",
                pattern_model={},
            ),
        ])

        db.commit()

    yield SessionLocal

    engine.dispose()


@pytest.fixture
def db(db_factory):
    with db_factory() as session:
        yield session


# 1. Default threshold

def test_default_threshold(db):
    assert get_threshold(db, "user-1") == pytest.approx(0.65)


# 2. Accepted intervention

def test_accepted_increases_threshold(db):
    result = update_threshold(db, "user-1", "accepted")

    assert result == pytest.approx(0.67)
    assert get_threshold(db, "user-1") == pytest.approx(0.67)


# 3. Dismissed intervention

def test_dismissed_decreases_threshold(db):
    result = update_threshold(db, "user-1", "dismissed")

    assert result == pytest.approx(0.63)
    assert get_threshold(db, "user-1") == pytest.approx(0.63)


# 4. Neutral responses

@pytest.mark.parametrize(
    "response",
    ["snoozed", "overridden", "reported", "ignored"],
)
def test_neutral_responses(db, response):
    update_threshold(db, "user-1", "accepted")

    result = update_threshold(db, "user-1", response)

    assert result == pytest.approx(0.67)


# 5. Upper threshold limit

def test_upper_threshold_limit(db):
    for _ in range(20):
        update_threshold(db, "user-1", "accepted")

    assert get_threshold(db, "user-1") == pytest.approx(0.80)


# 6. Lower threshold limit

def test_lower_threshold_limit(db):
    for _ in range(20):
        update_threshold(db, "user-1", "dismissed")

    assert get_threshold(db, "user-1") == pytest.approx(0.50)


# 7. User isolation

def test_user_isolation(db):
    update_threshold(db, "user-1", "accepted")
    update_threshold(db, "user-1", "accepted")

    assert get_threshold(db, "user-1") == pytest.approx(0.69)
    assert get_threshold(db, "user-2") == pytest.approx(0.65)


# 8. Preserve existing learned parameters

def test_preserves_learned_parameters(db):
    update_threshold(db, "user-1", "accepted")

    user = db.get(User, "user-1")

    params = user.pattern_model["parameters"]

    assert params["ultradian_cycle_minutes"] == 90
    assert params["trough_minute"] == 45
    assert params["adaptive_threshold"] == pytest.approx(0.67)

    assert user.pattern_model["schema_version"] == "learning_v3"


# 9. Persistence across database sessions

def test_persistence_across_database_sessions(db_factory):
    with db_factory() as first_session:
        update_threshold(
            first_session,
            "user-1",
            "accepted",
        )

    with db_factory() as second_session:
        assert get_threshold(
            second_session,
            "user-1",
        ) == pytest.approx(0.67)

        update_threshold(
            second_session,
            "user-1",
            "accepted",
        )

    with db_factory() as third_session:
        assert get_threshold(
            third_session,
            "user-1",
        ) == pytest.approx(0.69)


# 10. Invalid response

def test_invalid_response(db):
    with pytest.raises(ValueError):
        update_threshold(db, "user-1", "invalid")

    assert get_threshold(db, "user-1") == pytest.approx(0.65)


# 11. Non-string response

def test_non_string_response(db):
    with pytest.raises(ValueError):
        update_threshold(db, "user-1", None)


# 12. Unknown user update

def test_unknown_user_update(db):
    with pytest.raises(ValueError):
        update_threshold(db, "unknown-user", "accepted")


# 13. Unknown user lookup

def test_unknown_user_lookup(db):
    with pytest.raises(ValueError):
        get_threshold(db, "unknown-user")


# 14. Response normalization

def test_response_normalization(db):
    result = update_threshold(
        db,
        "user-1",
        "  ACCEPTED  ",
    )

    assert result == pytest.approx(0.67)


# 15. Multiple sequential adjustments

def test_sequential_adjustments(db):
    responses = [
        "accepted",
        "accepted",
        "dismissed",
        "snoozed",
        "reported",
    ]

    for response in responses:
        update_threshold(db, "user-1", response)

    assert get_threshold(db, "user-1") == pytest.approx(0.67)
