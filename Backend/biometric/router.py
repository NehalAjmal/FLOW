from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from db_models.base import get_db
from db_models.biometric import BiometricReading
from auth.dependencies import get_current_user
from db_models.user import User
from .schemas import BiometricIngestRequest, BiometricIngestResponse, LatestBiometricResponse

from sessions.service import verify_session_ownership, current_camera
from settings_app.service import feature_allowed

router = APIRouter()

def _compute_fatigue_signal(
    ear: Optional[float],
    hr: Optional[float],
    hrv: Optional[float],
) -> float:
    """
    Combine EAR, HR, HRV into a single 0-1 fatigue signal.
    Higher = more fatigued.
    Mirrors the logic in engine/biometric.py but works standalone.
    """
    score = 0.0
    count = 0

    if ear is not None:
        # EAR < 0.2 = very closed eyes = high fatigue
        ear_fatigue = max(0.0, min(1.0, 1.0 - (ear / 0.35)))
        score += ear_fatigue
        count += 1

    if hr is not None:
        # Elevated HR (above 90) = fatigue signal
        hr_fatigue = max(0.0, min(1.0, (hr - 60) / 40))
        score += hr_fatigue
        count += 1

    if hrv is not None:
        # Low HRV = fatigue (inverse relationship)
        hrv_fatigue = max(0.0, min(1.0, 1.0 - (hrv / 80)))
        score += hrv_fatigue
        count += 1

    return round(score / count, 3) if count > 0 else 0.5


@router.post("/ingest", response_model=BiometricIngestResponse)
def ingest_biometric(
    payload: BiometricIngestRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Receive a biometric reading from Apple Watch, rPPG, or the ML engine.
    Stores it in the DB and returns the computed fatigue signal.
    """
    session = verify_session_ownership(db, payload.session_id, current_user.id)
    if session.end_time is not None:
        raise HTTPException(409, "Session ended")
    if (payload.source != "apple_watch" or payload.ear_value is not None) and not feature_allowed(db, current_user.id, "camera"):
        raise HTTPException(403, "camera_consent_required")
    fatigue_signal = _compute_fatigue_signal(
        ear=payload.ear_value,
        hr=payload.heart_rate_bpm,
        hrv=payload.hrv_sdnn,
    )

    reading = BiometricReading(
        user_id=current_user.id,
        session_id=payload.session_id,
        heart_rate_bpm=payload.heart_rate_bpm,
        hrv_sdnn=payload.hrv_sdnn,
        ear_value=payload.ear_value,
        source=payload.source,
        confidence=payload.confidence,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    return BiometricIngestResponse(
        status="ok",
        reading_id=reading.id,
        fatigue_signal=fatigue_signal,
    )


@router.get("/latest", response_model=LatestBiometricResponse)
def get_latest_biometric(
    session_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Returns the most recent biometric reading for a session.
    Checks user-owned database readings and session-specific camera metrics.
    """
    session = verify_session_ownership(db, session_id, current_user.id) if session_id else None
    # Try DB first
    query = db.query(BiometricReading).filter(BiometricReading.user_id == current_user.id)
    if not feature_allowed(db, current_user.id, "camera"):
        query = query.filter(BiometricReading.source == "apple_watch", BiometricReading.ear_value.is_(None))
    if session_id:
        query = query.filter(BiometricReading.session_id == session_id)

    reading = query.order_by(BiometricReading.recorded_at.desc()).first()

    if reading:
        fatigue_signal = _compute_fatigue_signal(
            ear=reading.ear_value,
            hr=reading.heart_rate_bpm,
            hrv=reading.hrv_sdnn,
        )
        return LatestBiometricResponse(
            heart_rate_bpm=reading.heart_rate_bpm,
            hrv_sdnn=reading.hrv_sdnn,
            ear_value=reading.ear_value,
            fatigue_signal=fatigue_signal,
            has_data=True,
            source=reading.source,
        )

    state = current_camera(db, session) if session else {}
    if any(state.get(k) is not None for k in ("ear", "fatigue_score", "heart_rate_bpm")):
        return LatestBiometricResponse(heart_rate_bpm=state.get("heart_rate_bpm"), hrv_sdnn=None,
            ear_value=state.get("ear"), fatigue_signal=state.get("fatigue_score"), has_data=True, source="webcam")

    # No data anywhere — honest defaults, never invented values
    return LatestBiometricResponse(
        heart_rate_bpm=None,
        hrv_sdnn=None,
        ear_value=None,
        fatigue_signal=None,
        has_data=False,
        source=None,
    )
