# insights/router.py
# Shapes from frontend/CONTRACT_NOTES.md section 5.

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.user import User
from insights import service

router = APIRouter()


@router.get("/user/dashboard")
def dashboard(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return service.dashboard(db, current_user)


@router.get("/user/patterns")
def patterns(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return service.patterns(db, current_user)


@router.get("/forecast")
def forecast(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return service.forecast(db, current_user)


@router.get("/user/day")
def day(date_: date = Query(..., alias="date"), db: DBSession = Depends(get_db),
        current_user: User = Depends(get_current_user)):
    return service.day(db, current_user, date_)


@router.get("/user/month")
def month(month_: str = Query(..., alias="month", pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
          db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    year, mon = map(int, month_.split("-"))
    return service.month(db, current_user, year, mon)
