# breaks_app/router.py
# Shapes from frontend/CONTRACT_NOTES.md section 4 (and /session/{id}/resumption from section 3).

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from breaks_app import service
from db_models.base import get_db
from db_models.breaks import Break
from db_models.session import Session
from db_models.user import User

router = APIRouter()


class BreakStartRequest(BaseModel):
    session_id: str
    intervention_id: Optional[str] = None     # set when the break came from a prompt


class BreakEndRequest(BaseModel):
    actual_minutes: Optional[int] = Field(default=None, ge=0, le=240)


class RatingRequest(BaseModel):
    session_id: str
    kind: Literal["focus", "fatigue", "post_break_focus"]
    value: int = Field(ge=1, le=5)
    context_id: Optional[str] = None


class ResumptionRequest(BaseModel):
    break_id: str
    seconds_to_first_edit: float = Field(ge=0, le=3600)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _own_session(db: DBSession, session_id: str, user: User) -> Session:
    s = db.get(Session, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


def _own_break(db: DBSession, break_id: str, user: User) -> Break:
    b = db.get(Break, break_id)
    if b is None or b.session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Break not found")
    return b


def _live(action: str, session_id: str) -> None:
    # Lazy import: sessions.service loads the camera/ML code (see interventions/router.py).
    from sessions import service as sessions_service
    getattr(sessions_service, action)(session_id)


@router.post("/breaks/start")
def start(payload: BreakStartRequest, db: DBSession = Depends(get_db),
          current_user: User = Depends(get_current_user)):
    session = _own_session(db, payload.session_id, current_user)
    try:
        row = service.start_break(db, session, payload.intervention_id, _now())
    except service.BreakError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _live("clear_live_intervention", session.id)
    return {"break_id": row.id}


@router.post("/breaks/{break_id}/end")
def end(break_id: str, payload: BreakEndRequest, db: DBSession = Depends(get_db),
        current_user: User = Depends(get_current_user)):
    row = _own_break(db, break_id, current_user)
    try:
        service.end_break(db, row, payload.actual_minutes, _now())
    except service.BreakError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _live("reset_ultradian", row.session_id)
    # Restoration needs a few minutes of work after the break, so it is usually still null here.
    return {"restoration_score": row.restoration_score}


@router.get("/breaks")
def list_breaks(session_id: str, db: DBSession = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    _own_session(db, session_id, current_user)
    return service.summary(db, session_id)


@router.post("/ratings")
def rate(payload: RatingRequest, db: DBSession = Depends(get_db),
         current_user: User = Depends(get_current_user)):
    _own_session(db, payload.session_id, current_user)
    row = service.add_rating(db, current_user.id, payload.session_id, payload.kind,
                             payload.value, payload.context_id, _now())
    return {"id": row.id}


@router.post("/session/{session_id}/resumption")
def resumption(session_id: str, payload: ResumptionRequest, db: DBSession = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    _own_session(db, session_id, current_user)
    row = _own_break(db, payload.break_id, current_user)
    if row.session_id != session_id:
        raise HTTPException(status_code=404, detail="Break not found")
    service.record_resumption(db, row, payload.seconds_to_first_edit)
    return {"status": "ok"}
