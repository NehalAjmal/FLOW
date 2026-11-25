# schedules/router.py
# /user/schedules CRUD, shapes from frontend/CONTRACT_NOTES.md "Schedules (routines)".

import re
from datetime import datetime, timezone
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.schedule import Schedule
from db_models.user import User

router = APIRouter()

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start: str
    end: str
    weekdays: List[int] = Field(min_length=1, max_length=7)
    demand: Literal["light", "moderate", "heavy"]
    enabled: bool = True

    @field_validator("start", "end")
    @classmethod
    def hhmm(cls, v):
        if not HHMM.match(v):
            raise ValueError("use 24-hour HH:mm")
        return v

    @field_validator("weekdays")
    @classmethod
    def days(cls, v):
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("weekdays are 1 (Mon) to 7 (Sun)")
        return sorted(set(v))

    @model_validator(mode="after")
    def end_after_start(self):
        # "HH:mm" strings compare correctly as text. Overnight schedules aren't supported.
        if self.end <= self.start:
            raise ValueError("end must be after start, on the same day")
        return self


def _out(s: Schedule) -> dict:
    return {"id": s.id, "name": s.name, "start": s.start, "end": s.end,
            "weekdays": s.weekdays, "demand": s.demand, "enabled": s.enabled}


def _own(db: DBSession, schedule_id: str, user: User) -> Schedule:
    s = db.get(Schedule, schedule_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return s


@router.get("/user/schedules")
def list_schedules(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(Schedule).filter(Schedule.user_id == current_user.id).order_by(Schedule.start).all()
    return {"schedules": [_out(s) for s in rows]}


@router.post("/user/schedules")
def create_schedule(payload: ScheduleIn, db: DBSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    s = Schedule(user_id=current_user.id, created_at=datetime.now(timezone.utc), **payload.model_dump())
    db.add(s)
    db.commit()
    return _out(s)


@router.put("/user/schedules/{schedule_id}")
def update_schedule(schedule_id: str, payload: ScheduleIn, db: DBSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    s = _own(db, schedule_id, current_user)
    for key, value in payload.model_dump().items():
        setattr(s, key, value)
    db.commit()
    return _out(s)


@router.delete("/user/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, db: DBSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    db.delete(_own(db, schedule_id, current_user))
    db.commit()
    return Response(status_code=204)
