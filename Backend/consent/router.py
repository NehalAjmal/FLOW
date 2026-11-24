from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from db_models.base import get_db
from db_models.user import User
from auth.dependencies import get_current_user
from .schemas import ConsentResponse, ScopeStatus, UpdateConsentRequest
from .service import (
    get_user_consent, set_user_consent,
    CURRENT_POLICY_VERSION, KNOWN_SCOPES
)

router = APIRouter(tags=["Consent"])


@router.get("", response_model=ConsentResponse)
@router.get("/", response_model=ConsentResponse)
def get_consent(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Get current consent status across all 5 scopes for the authenticated user.
    """
    scopes = get_user_consent(db, current_user.id)
    return ConsentResponse(
        policy_version=CURRENT_POLICY_VERSION,
        scopes=scopes,
    )


@router.put("/{scope}", response_model=ScopeStatus)
def update_consent(
    scope: str,
    payload: UpdateConsentRequest,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Update consent grant for a specific scope (behavior, camera, calendar, llm, team_aggregate).
    """
    if scope not in KNOWN_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope '{scope}'. Allowed scopes: {KNOWN_SCOPES}",
        )

    updated = set_user_consent(
        db=db,
        user_id=current_user.id,
        scope=scope,
        granted=payload.granted,
        policy_version=payload.policy_version,
    )
    return ScopeStatus(**updated)
