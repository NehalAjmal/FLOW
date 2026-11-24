# admin/invites.py
# Single-use invite links that an admin makes for their team.
#
# The secret in the link is shown once (when it's made) and only its sha256
# hash is stored. Registering with the link puts the new person on the team,
# marks the link used, and turns on their "Share with my team" consent,
# because the invite page told them exactly what the admin sees.

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from config import settings
from db_models.invite import Invite
from db_models.user import User

DEFAULT_HOURS = 24 * 7
MAX_HOURS = 24 * 30


class InviteError(Exception):
    """reason is one of: invalid | expired | used"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def link(token: str) -> str:
    # The Flutter route for the invite landing page is /invite?token=...
    return f"{settings.app_url.rstrip('/')}/invite?token={token}"


def to_json(inv: Invite, url: Optional[str] = None) -> dict:
    out = {"id": inv.id, "created_at": _aware(inv.created_at).isoformat(),
           "expires_at": _aware(inv.expires_at).isoformat(), "used": inv.used_at is not None}
    if url:
        out["url"] = url          # only on create; the hash can't give it back later
    return out


def create(db: DBSession, admin: User, hours: int, now: Optional[datetime] = None) -> Tuple[Invite, str]:
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(24)
    inv = Invite(team_id=admin.team_id, created_by=admin.id, token_hash=_hash(token),
                 created_at=now, expires_at=now + timedelta(hours=hours))
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv, link(token)


def list_for_team(db: DBSession, team_id: str):
    return (db.query(Invite).filter(Invite.team_id == team_id)
            .order_by(Invite.created_at.desc()).all())


def revoke(db: DBSession, admin: User, invite_id: str) -> bool:
    inv = db.query(Invite).filter(Invite.id == invite_id, Invite.team_id == admin.team_id).first()
    if not inv:
        return False
    db.delete(inv)
    db.commit()
    return True


def check(db: DBSession, token: str, now: Optional[datetime] = None) -> Invite:
    """The invite behind a link, if it can still be used. Accepts the whole link too."""
    now = now or datetime.now(timezone.utc)
    token = (token or "").strip()
    if "token=" in token:
        token = token.split("token=", 1)[1].split("&", 1)[0]
    inv = db.query(Invite).filter(Invite.token_hash == _hash(token)).first() if token else None
    if not inv:
        raise InviteError("invalid")
    if inv.used_at is not None:
        raise InviteError("used")
    if _aware(inv.expires_at) <= now:
        raise InviteError("expired")
    return inv


def mark_used(db: DBSession, inv: Invite, user_id: str) -> None:
    inv.used_at = datetime.now(timezone.utc)
    inv.used_by = user_id
    db.commit()
