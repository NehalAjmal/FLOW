# engine/threshold.py

from sqlalchemy.orm import Session as DBSession

from db_models.user import User
from engine.adaptive_threshold import AdaptiveThresholdEngine


SUPPORTED_RESPONSES = {
    "accepted",
    "dismissed",
    "snoozed",
    "overridden",
    "reported",
    "ignored",
}


def get_threshold(db: DBSession, user_id: str) -> float:
    """
    Return the user's personalized intervention threshold.

    If the user has no learned threshold, return the default.
    """

    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise ValueError(f"User not found: {user_id}")

    pattern_model = user.pattern_model or {}
    parameters = pattern_model.get("parameters") or {}

    engine = AdaptiveThresholdEngine(
        threshold=parameters.get("adaptive_threshold")
    )

    return engine.get_threshold()


def update_threshold(
    db: DBSession,
    user_id: str,
    response: str,
) -> float:
    """
    Update and persist a user's personalized threshold.

    Accepted:
        Increase intervention sensitivity.

    Dismissed:
        Decrease intervention sensitivity.

    Snoozed, overridden, reported, ignored:
        Preserve the current threshold.

    The threshold is always bounded between 0.50 and 0.80.
    """

    if not isinstance(response, str):
        raise ValueError("Response must be a string")

    response = response.strip().lower()

    if response not in SUPPORTED_RESPONSES:
        raise ValueError(f"Invalid intervention response: {response}")

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .first()
    )

    if user is None:
        raise ValueError(f"User not found: {user_id}")

    # Copy dictionaries so SQLAlchemy detects JSON changes.
    pattern_model = dict(user.pattern_model or {})
    parameters = dict(pattern_model.get("parameters") or {})

    engine = AdaptiveThresholdEngine(
        threshold=parameters.get("adaptive_threshold")
    )

    if response in {"accepted", "dismissed"}:
        new_threshold = engine.update(response)
    else:
        new_threshold = engine.get_threshold()

    parameters["adaptive_threshold"] = new_threshold

    pattern_model["parameters"] = parameters
    pattern_model.setdefault("schema_version", "learning_v3")

    user.pattern_model = pattern_model

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return new_threshold
