# settings_app/service.py
# Settings rules shared by the router and the rest of the app.

from sqlalchemy.orm import Session as DBSession

from consent.service import has_consent
from interventions.service import get_settings

DEFAULT_SNOOZE_OPTIONS = [5, 10, 15]

# setting name -> the consent scope it needs
NEEDS_CONSENT = {"camera_enabled": "camera", "calendar_enabled": "calendar", "llm_enabled": "llm"}


def feature_allowed(db: DBSession, user_id: str, feature: str) -> bool:
    """camera / calendar / llm are on only if the user consented AND left the switch on.
    Consent is the legal permission; the switch lets them turn it off without revoking it."""
    if not has_consent(db, user_id, feature):
        return False
    return bool(getattr(get_settings(db, user_id), f"{feature}_enabled"))


def settings_out(db: DBSession, user_id: str) -> dict:
    s = get_settings(db, user_id)
    return {
        "delivery_mode": s.delivery_mode or "advisory",
        "break_length_sec": s.break_length_sec or 300,
        "quiet_hours": (
            {"start": s.quiet_start, "end": s.quiet_end}
            if s.quiet_start and s.quiet_end else None
        ),
        "timezone": s.timezone,
        # Report what is actually in effect, so the app never shows "on" without consent.
        "camera_enabled": feature_allowed(db, user_id, "camera"),
        "calendar_enabled": feature_allowed(db, user_id, "calendar"),
        "llm_enabled": feature_allowed(db, user_id, "llm"),
        "snooze_options": s.snooze_options or DEFAULT_SNOOZE_OPTIONS,
    }
