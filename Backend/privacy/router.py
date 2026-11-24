# privacy/router.py
# Shapes from frontend/CONTRACT_NOTES.md section 6.

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session as DBSession

from auth.dependencies import get_current_user
from db_models.base import get_db
from db_models.data_export import DataExport
from db_models.session import Session
from db_models.user import User
from privacy import service

router = APIRouter()


def _export_out(e: DataExport) -> dict:
    return {
        "id": e.id,
        "status": e.status,
        "download_url": f"/me/data-export/{e.id}/download" if e.status == "ready" else None,
    }


def _own_export(db: DBSession, export_id: str, user: User) -> DataExport:
    e = db.get(DataExport, export_id)
    if e is None or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="Export not found")
    return e


def _stop_live_sessions(db: DBSession, user_id: str) -> None:
    # Lazy import: sessions.service loads the camera/ML code.
    from sessions import service as sessions_service
    running = db.query(Session.id).filter(Session.user_id == user_id, Session.end_time.is_(None)).all()
    for (sid,) in running:
        sessions_service.drop_live_session(sid)


@router.get("/me/data-summary")
def data_summary(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return service.data_summary(db, current_user.id)


@router.post("/me/data-export")
def start_export(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Built straight away: one user's data is small. The pending/ready status
    # still matches the contract, so this could move to a background job later.
    return _export_out(service.create_export(db, current_user.id))


@router.get("/me/data-export/{export_id}")
def export_status(export_id: str, db: DBSession = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    return _export_out(_own_export(db, export_id, current_user))


@router.get("/me/data-export/{export_id}/download")
def download_export(export_id: str, db: DBSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    e = _own_export(db, export_id, current_user)
    if e.status != "ready":
        raise HTTPException(status_code=409, detail=f"Export is {e.status}")
    return Response(
        content=json.dumps(e.payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="flow-data-{e.created_at:%Y-%m-%d}.json"'},
    )


@router.delete("/me", status_code=204)
def delete_me(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    _stop_live_sessions(db, current_user.id)
    service.delete_account(db, current_user)
    return Response(status_code=204)
