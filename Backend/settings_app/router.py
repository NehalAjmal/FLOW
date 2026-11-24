# settings_app/router.py
# /pause and /settings. Only the parts gating needs for now;
# Task 4 adds delivery mode, camera, calendar and LLM switches here.

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.user import User
from interventions.service import get_settings, _aware

router = APIRouter()

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ── Request / response shapes (match frontend/CONTRACT_NOTES.md §2) ──

class PauseRequest(BaseModel):
    minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)
    until_end_of_day: bool = False


class QuietHours(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def must_be_hhmm(cls, v: str) -> str:
        if not HHMM.match(v):
            raise ValueError("use 24-hour HH:mm, e.g. 22:00")
        return v


class SettingsUpdate(BaseModel):
    # Every field is optional: PUT only changes what you send.
    quiet_hours: Optional[QuietHours] = None
    clear_quiet_hours: bool = False
    timezone: Optional[str] = None


def _settings_out(s) -> dict:
    return {
        "timezone": s.timezone,
        "quiet_hours": (
            {"start": s.quiet_start, "end": s.quiet_end}
            if s.quiet_start and s.quiet_end else None
        ),
    }


# ── Pause ─────────────────────────────────────────────

@router.post("/pause")
def pause(
    payload: PauseRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = get_settings(db, current_user.id)
    now = datetime.now(timezone.utc)

    if payload.until_end_of_day:
        tz = ZoneInfo(s.timezone)
        local_midnight = (now.astimezone(tz) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        until = local_midnight.astimezone(timezone.utc)
    elif payload.minutes:
        until = now + timedelta(minutes=payload.minutes)
    else:
        raise HTTPException(status_code=422, detail="Send minutes or until_end_of_day")

    s.paused_until = until
    db.commit()
    return {"paused": True, "until": until.isoformat()}


@router.get("/pause")
def pause_status(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = get_settings(db, current_user.id)
    until = _aware(s.paused_until)
    paused = until is not None and until > datetime.now(timezone.utc)
    return {"paused": paused, "until": until.isoformat() if paused else None}


@router.delete("/pause", status_code=204)
def resume(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = get_settings(db, current_user.id)
    s.paused_until = None
    db.commit()
    return Response(status_code=204)


# ── Settings (quiet hours + time zone for now) ─────────

@router.get("/settings")
def read_settings(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _settings_out(get_settings(db, current_user.id))


@router.put("/settings")
def update_settings(
    payload: SettingsUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = get_settings(db, current_user.id)

    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=422, detail=f"Unknown time zone: {payload.timezone}")
        s.timezone = payload.timezone

    if payload.clear_quiet_hours:
        s.quiet_start = s.quiet_end = None
    elif payload.quiet_hours is not None:
        s.quiet_start = payload.quiet_hours.start
        s.quiet_end = payload.quiet_hours.end

    db.commit()
    return _settings_out(s)
