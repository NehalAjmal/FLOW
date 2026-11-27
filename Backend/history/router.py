# history/router.py
# GET /sessions and GET /session/{id}/replay, shapes from frontend/CONTRACT_NOTES.md section 3.

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.session import Session
from db_models.user import User
from history import service

router = APIRouter()


@router.get("/sessions")
def list_sessions(
    page: int = Query(1, ge=1),
    from_: Optional[date] = Query(None, alias="from"),   # "from" is a Python keyword, hence the alias
    to: Optional[date] = Query(None),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start = datetime.combine(from_, time.min, tzinfo=timezone.utc) if from_ else None
    end = datetime.combine(to + timedelta(days=1), time.min, tzinfo=timezone.utc) if to else None  # "to" is inclusive
    return service.list_sessions(db, current_user.id, page, start, end)


@router.get("/session/{session_id}/replay")
def replay(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.get(Session, session_id)
    if s is None or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return service.replay(db, s)
