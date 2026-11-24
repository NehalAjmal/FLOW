# privacy/service.py
# What FLOW stores about a user: a summary, a full export, and deleting all of it.

from datetime import datetime, timezone

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session as DBSession

from db_models.audit_log import AuditLog
from db_models.biometric import BiometricReading
from db_models.breaks import Break
from db_models.calendar_cache import CalendarCache
from db_models.consent import ConsentGrant
from db_models.data_export import DataExport
from db_models.intervention import Intervention
from db_models.rating import Rating
from db_models.refresh_token import RefreshToken
from db_models.schedule import Schedule
from db_models.session import Session
from db_models.user import User
from db_models.user_settings import UserSettings

# Never put these in an export: they are secrets, not "your data".
SECRET_COLUMNS = {"password_hash", "mfa_secret", "token_hash", "token"}


def _row(obj) -> dict:
    """Every column of a database row as a plain dict, minus secrets."""
    out = {}
    for col in sa_inspect(obj).mapper.column_attrs:
        if col.key in SECRET_COLUMNS:
            continue
        value = getattr(obj, col.key)
        out[col.key] = value.isoformat() if isinstance(value, datetime) else value
    return out


def _session_ids(db: DBSession, user_id: str) -> list:
    return [sid for (sid,) in db.query(Session.id).filter(Session.user_id == user_id).all()]


def _categories(db: DBSession, user_id: str) -> list:
    """(name, description, query) for every kind of data tied to the user."""
    sids = _session_ids(db, user_id)
    return [
        ("profile", "Name, email, role, team and learned rhythm",
         db.query(User).filter(User.id == user_id)),
        ("settings", "Your Settings screen choices and pause",
         db.query(UserSettings).filter(UserSettings.user_id == user_id)),
        ("consent", "What you agreed to and when",
         db.query(ConsentGrant).filter(ConsentGrant.user_id == user_id)),
        ("sessions", "Focus sessions, including the 30-second activity log (counts only, no keystroke content)",
         db.query(Session).filter(Session.user_id == user_id)),
        ("prompts", "Prompts FLOW showed you and how you answered",
         db.query(Intervention).filter(Intervention.user_id == user_id)),
        ("breaks", "Breaks, restoration scores and resumption times",
         db.query(Break).filter(Break.session_id.in_(sids))),
        ("ratings", "Your 1-5 focus and fatigue ratings",
         db.query(Rating).filter(Rating.user_id == user_id)),
        ("heart_rate", "Heart-rate readings (camera or watch)",
         db.query(BiometricReading).filter(BiometricReading.user_id == user_id)),
        ("calendar", "Cached calendar events",
         db.query(CalendarCache).filter(CalendarCache.user_id == user_id)),
        ("schedules", "Your repeating planned sessions",
         db.query(Schedule).filter(Schedule.user_id == user_id)),
    ]


def data_summary(db: DBSession, user_id: str) -> dict:
    return {
        "categories": [
            # No retention policy has been decided yet, so we don't invent one:
            # null = kept until you delete your account.
            {"name": name, "description": desc, "item_count": q.count(), "retention_days": None}
            for name, desc, q in _categories(db, user_id)
        ]
    }


def create_export(db: DBSession, user_id: str) -> DataExport:
    now = datetime.now(timezone.utc)
    export = DataExport(user_id=user_id, status="pending", created_at=now)
    db.add(export)
    db.commit()
    try:
        export.payload = {
            "exported_at": now.isoformat(),
            **{name: [_row(r) for r in q.all()] for name, _, q in _categories(db, user_id)},
        }
        export.status = "ready"
    except Exception as e:                   # never leave it stuck on "pending"
        print("data export failed:", e)
        export.status = "failed"
    db.commit()
    return export


def delete_account(db: DBSession, user: User) -> None:
    """Remove everything tied to the user, then the user.
    Rows without an ORM relationship to User are deleted by hand, so this
    works the same on MySQL and in the SQLite tests."""
    uid = user.id
    sids = _session_ids(db, uid)

    db.query(DataExport).filter(DataExport.user_id == uid).delete(synchronize_session=False)
    db.query(Rating).filter(Rating.user_id == uid).delete(synchronize_session=False)
    db.query(Intervention).filter(Intervention.user_id == uid).delete(synchronize_session=False)
    db.query(UserSettings).filter(UserSettings.user_id == uid).delete(synchronize_session=False)
    db.query(Schedule).filter(Schedule.user_id == uid).delete(synchronize_session=False)
    if sids:
        db.query(Break).filter(Break.session_id.in_(sids)).delete(synchronize_session=False)
        db.query(BiometricReading).filter(BiometricReading.session_id.in_(sids)).delete(synchronize_session=False)
    db.query(BiometricReading).filter(BiometricReading.user_id == uid).delete(synchronize_session=False)
    db.query(Session).filter(Session.user_id == uid).delete(synchronize_session=False)
    db.query(CalendarCache).filter(CalendarCache.user_id == uid).delete(synchronize_session=False)
    db.query(ConsentGrant).filter(ConsentGrant.user_id == uid).delete(synchronize_session=False)
    db.query(RefreshToken).filter(RefreshToken.user_id == uid).delete(synchronize_session=False)
    # Admin audit entries stay (they're the team's record), but no longer point at this person.
    db.query(AuditLog).filter(AuditLog.actor_id == uid).update(
        {AuditLog.actor_id: None, AuditLog.actor_email: None}, synchronize_session=False)

    db.expire_all()   # forget cached relationships before deleting the user row
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()
