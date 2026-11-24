from datetime import datetime, timezone
from typing import Dict, Optional
from sqlalchemy.orm import Session
from db_models.consent import ConsentGrant

CURRENT_POLICY_VERSION = "1.0"
KNOWN_SCOPES = ["behavior", "camera", "calendar", "llm", "team_aggregate"]


def get_user_consent(db: Session, user_id: str) -> Dict[str, dict]:
    """
    Returns all 5 consent scopes for the user.
    A grant made under an older policy version than CURRENT_POLICY_VERSION
    evaluates to granted: False per CONTRACT_NOTES.md §2.
    """
    grants = db.query(ConsentGrant).filter(ConsentGrant.user_id == user_id).all()
    grant_map = {g.scope: g for g in grants}

    now_iso = datetime.now(timezone.utc).isoformat()
    result = {}
    for scope in KNOWN_SCOPES:
        if scope in grant_map:
            g = grant_map[scope]
            is_valid_version = (g.policy_version == CURRENT_POLICY_VERSION)
            ts = g.updated_at.isoformat() if g.updated_at else now_iso
            result[scope] = {
                "granted": bool(g.granted and is_valid_version),
                "version": g.policy_version,
                "timestamp": ts,
            }
        else:
            result[scope] = {
                "granted": False,
                "version": CURRENT_POLICY_VERSION,
                "timestamp": now_iso,
            }
    return result


def set_user_consent(
    db: Session,
    user_id: str,
    scope: str,
    granted: bool,
    policy_version: Optional[str] = None
) -> dict:
    """
    Sets or updates a consent grant for the given scope.
    """
    if scope not in KNOWN_SCOPES:
        raise ValueError(f"Unknown consent scope: '{scope}'. Allowed: {KNOWN_SCOPES}")

    ver = policy_version or CURRENT_POLICY_VERSION
    grant = db.query(ConsentGrant).filter(
        ConsentGrant.user_id == user_id,
        ConsentGrant.scope == scope
    ).first()

    now = datetime.now(timezone.utc)
    if not grant:
        grant = ConsentGrant(
            user_id=user_id,
            scope=scope,
            granted=granted,
            policy_version=ver,
            updated_at=now,
        )
        db.add(grant)
    else:
        grant.granted = granted
        grant.policy_version = ver
        grant.updated_at = now

    db.commit()
    db.refresh(grant)

    is_valid_version = (grant.policy_version == CURRENT_POLICY_VERSION)
    return {
        "granted": bool(grant.granted and is_valid_version),
        "version": grant.policy_version,
        "timestamp": grant.updated_at.isoformat() if grant.updated_at else now.isoformat(),
    }


def has_consent(db: Session, user_id: str, scope: str) -> bool:
    """
    Helper for enforcement points: returns True iff granted AND matching policy_version.
    """
    grant = db.query(ConsentGrant).filter(
        ConsentGrant.user_id == user_id,
        ConsentGrant.scope == scope
    ).first()
    if not grant:
        return False
    return bool(grant.granted and grant.policy_version == CURRENT_POLICY_VERSION)
