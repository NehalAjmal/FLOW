# interventions/router.py
# /intervention/* endpoints, shapes from frontend/CONTRACT_NOTES.md section 4.

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.intervention import Intervention
from db_models.user import User
from interventions import service
from interventions.threshold_hook import on_response

router = APIRouter()


class RespondRequest(BaseModel):
    response: Literal["accepted", "dismissed", "snoozed"]
    snooze_minutes: Optional[int] = Field(default=None, ge=1, le=120)


class OverrideRequest(BaseModel):
    reason: Literal["incident", "deploy", "pairing", "other"]


class ReportRequest(BaseModel):
    reason: Literal["wrong_time", "in_meeting", "too_frequent", "not_needed", "other"]
    free_text: Optional[str] = None


def _clear_live(session_id: str) -> None:
    # Imported here, not at the top: sessions.service loads the camera/ML code,
    # and this keeps that out of the way when the tests import this router.
    from sessions.service import clear_live_intervention
    clear_live_intervention(session_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(db: DBSession, intervention_id: str, user: User) -> Intervention:
    row = service.get_for_user(db, intervention_id, user.id)
    if row is None:
        # Same 404 whether it doesn't exist or belongs to someone else,
        # so nobody can probe for other users' prompt ids.
        raise HTTPException(status_code=404, detail="Intervention not found")
    return row


def _out(row: Intervention, threshold: Optional[float] = None) -> dict:
    return {
        "id": row.id,
        "type": row.kind,
        "title": row.title,
        "message": row.message,
        "response": row.response,
        "snooze_until": row.snooze_until.isoformat() if row.snooze_until else None,
        "override_reason": row.override_reason,
        "report_reason": row.report_reason,
        "threshold": threshold,
    }


@router.get("/session/{session_id}/counts")
def counts(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from db_models.session import Session
    session = db.get(Session, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return service.session_counts(db, session_id)


@router.get("/{intervention_id}")
def read(
    intervention_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _out(_load(db, intervention_id, current_user))


@router.post("/{intervention_id}/respond")
def respond(
    intervention_id: str,
    payload: RespondRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _load(db, intervention_id, current_user)
    try:
        service.respond(db, row, payload.response, payload.snooze_minutes, _now())
    except service.AlreadyAnswered as e:
        raise HTTPException(status_code=409, detail=f"Already answered: {e}")
    _clear_live(row.session_id)
    threshold = on_response(db, current_user.id, payload.response)
    return _out(row, threshold)


@router.post("/{intervention_id}/override")
def override(
    intervention_id: str,
    payload: OverrideRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _load(db, intervention_id, current_user)
    try:
        service.override(db, row, payload.reason, _now())
    except service.AlreadyAnswered as e:
        raise HTTPException(status_code=409, detail=f"Already answered: {e}")
    _clear_live(row.session_id)
    threshold = on_response(db, current_user.id, "overridden")
    return _out(row, threshold)


@router.post("/{intervention_id}/report")
def report(
    intervention_id: str,
    payload: ReportRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _load(db, intervention_id, current_user)
    service.report(db, row, payload.reason, payload.free_text)
    _clear_live(row.session_id)
    threshold = on_response(db, current_user.id, "reported")
    return _out(row, threshold)
