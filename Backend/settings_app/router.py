# settings_app/router.py
# /pause and /settings, shapes from frontend/CONTRACT_NOTES.md section 2.

import re
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.user import User
from consent.service import has_consent
from interventions.service import get_settings, _aware
from settings_app.service import NEEDS_CONSENT, settings_out

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
    delivery_mode: Optional[Literal["advisory", "explained", "lock"]] = None
    break_length_sec: Optional[int] = Field(default=None, ge=60, le=3600)
    quiet_hours: Optional[QuietHours] = None          # send null to turn quiet hours off
    timezone: Optional[str] = None
    camera_enabled: Optional[bool] = None
    calendar_enabled: Optional[bool] = None
    llm_enabled: Optional[bool] = None
    snooze_options: Optional[List[int]] = Field(default=None, min_length=1, max_length=5)

    @field_validator("snooze_options")
    @classmethod
    def sensible_minutes(cls, v):
        if v is not None and any(m < 1 or m > 120 for m in v):
            raise ValueError("snooze options must be 1-120 minutes")
        return sorted(set(v)) if v is not None else v


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


# ── Settings ───────────────────────────────────────────

@router.get("/settings")
def read_settings(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return settings_out(db, current_user.id)


@router.put("/settings")
def update_settings(
    payload: SettingsUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = get_settings(db, current_user.id)
    sent = payload.model_fields_set        # the fields the client actually sent

    # The server enforces consent: a switch can't be turned on without it.
    for field, scope in NEEDS_CONSENT.items():
        if getattr(payload, field) is True and not has_consent(db, current_user.id, scope):
            raise HTTPException(status_code=403, detail=f"{scope}_consent_required")

    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=422, detail=f"Unknown time zone: {payload.timezone}")
        s.timezone = payload.timezone

    if "quiet_hours" in sent:
        if payload.quiet_hours is None:
            s.quiet_start = s.quiet_end = None
        else:
            s.quiet_start = payload.quiet_hours.start
            s.quiet_end = payload.quiet_hours.end

    for field in ("delivery_mode", "break_length_sec", "camera_enabled",
                  "calendar_enabled", "llm_enabled", "snooze_options"):
        value = getattr(payload, field)
        if value is not None:
            setattr(s, field, value)

    db.commit()
    return settings_out(db, current_user.id)
