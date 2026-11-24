from typing import Optional
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from db_models.base import get_db
from db_models.user import User
from db_models.team import Team
from db_models.refresh_token import RefreshToken
from config import settings

from auth.schemas import (
    RegisterRequest, LoginRequest,
    RegisterResponse, LoginResponse,
    GoogleAuthRequest, RefreshRequest, RefreshResponse,
    MFAVerifyRequest, MFAVerifyResponse, MFASetupResponse,
)
from auth.utils import (
    get_password_hash, verify_password, create_access_token,
    create_refresh_token, hash_token, REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY, ALGORITHM,
)
from auth.totp import generate_totp_secret, verify_totp_code, get_otpauth_url
from auth.dependencies import require_admin

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Helper ─────────────────────────────────────────────────────────────────────

def _issue_refresh_token(db: Session, user_id: str) -> str:
    raw_refresh = create_refresh_token()
    db_refresh = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(db_refresh)
    db.commit()
    return raw_refresh


def _resolve_team(
    db: Session,
    account_type: str,
    company_code: Optional[str] = None,
    admin_key: Optional[str] = None,
):
    if account_type == "admin":
        if not company_code or not admin_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin registration requires both company_code and a valid admin_key",
            )
        team = db.query(Team).filter(Team.company_code == company_code).first()
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid company code")
        if not verify_password(admin_key, team.admin_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin key. Admin self-registration is restricted.",
            )
        return "admin", team.id

    if account_type in ("company_employee", "employee"):
        if not company_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="company_code is required for this account type")
        team = db.query(Team).filter(Team.company_code == company_code).first()
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid company code")
        return "employee", team.id

    return "solo", None


# ── /register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email is already registered")

    role, team_id = _resolve_team(db, payload.account_type, payload.company_code, payload.admin_key)

    mfa_secret = generate_totp_secret() if role == "admin" else None

    new_user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        age=payload.age,
        sex=payload.sex,
        role=role,
        team_id=team_id,
        mfa_secret=mfa_secret,
        mfa_enabled=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_access_token(data={"sub": new_user.id, "role": new_user.role})
    refresh = _issue_refresh_token(db, new_user.id)

    return RegisterResponse(
        user_id=new_user.id,
        token=token,
        access_token=token,
        refresh_token=refresh,
        role=new_user.role,
        team_id=new_user.team_id,
        redirect_to="/dashboard",
    )


# ── /login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    # Consent check per CONTRACT_NOTES.md §1: consent_missing[]
    from consent.service import has_consent, KNOWN_SCOPES
    missing_consents = [scope for scope in KNOWN_SCOPES if not has_consent(db, user.id, scope)]

    # Admin MFA gate per CONTRACT_NOTES.md §1:
    # Admin login returns {mfa_required: true, mfa_token, role, team_id}
    if user.role == "admin":
        if not user.mfa_secret:
            user.mfa_secret = generate_totp_secret()
            db.commit()
            db.refresh(user)

        mfa_token = create_access_token(
            data={"sub": user.id, "purpose": "mfa_pending", "role": "admin"},
            expires_delta=timedelta(minutes=5),
        )
        return LoginResponse(
            user_id=user.id,
            role=user.role,
            team_id=user.team_id,
            redirect_to="/mfa",
            mfa_required=True,
            mfa_token=mfa_token,
            consent_missing=missing_consents,
        )

    token = create_access_token(data={"sub": user.id, "role": user.role})
    refresh = _issue_refresh_token(db, user.id)

    return LoginResponse(
        user_id=user.id,
        token=token,
        access_token=token,
        refresh_token=refresh,
        role=user.role,
        team_id=user.team_id,
        redirect_to="/dashboard",
        mfa_required=False,
        consent_missing=missing_consents,
    )


# ── /google ────────────────────────────────────────────────────────────────────

@router.post("/google", response_model=RegisterResponse, status_code=status.HTTP_200_OK)
def google_auth(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    try:
        id_info   = id_token.verify_oauth2_token(payload.token, google_requests.Request(), settings.google_client_id)
        email     = id_info["email"]
        full_name = id_info.get("name", "")
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid Google token")

    user = db.query(User).filter(User.email == email).first()

    if user:
        # Existing user — just issue a fresh token, no updates
        pass
    else:
        # New user — password + baselines required
        if not payload.password:
            raise HTTPException(status_code=400, detail="Password is required when registering via Google")

        role, team_id = _resolve_team(db, payload.account_type or "solo", payload.company_code, payload.admin_key)

        mfa_secret = generate_totp_secret() if role == "admin" else None

        user = User(
            full_name=full_name,
            email=email,
            password_hash=get_password_hash(payload.password),
            age=payload.age,       # ← now saved
            sex=payload.sex,       # ← now saved
            role=role,
            team_id=team_id,
            mfa_secret=mfa_secret,
            mfa_enabled=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token(data={"sub": user.id, "role": user.role})
    refresh = _issue_refresh_token(db, user.id)

    return RegisterResponse(
        user_id=user.id,
        token=token,
        access_token=token,
        refresh_token=refresh,
        role=user.role,
        team_id=user.team_id,
        redirect_to="/dashboard",
    )


# ── /refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=RefreshResponse, status_code=status.HTTP_200_OK)
def refresh_access_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    """
    Exchange a valid, unexpired, unrevoked refresh token for a fresh access token.
    Rotates the refresh token (revokes current, returns a new one).
    """
    token_hash = hash_token(payload.refresh_token)
    db_token = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash,
        RefreshToken.revoked == False,
    ).first()

    if not db_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    now = datetime.now(timezone.utc)
    exp = db_token.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    if exp < now:
        db_token.revoked = True
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Rotate: revoke current refresh token and issue a new pair
    db_token.revoked = True
    new_access = create_access_token(data={"sub": user.id, "role": user.role})
    new_refresh = _issue_refresh_token(db, user.id)

    return RefreshResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        token=new_access,
    )


# ── /logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_200_OK)
def logout_user(payload: RefreshRequest, db: Session = Depends(get_db)):
    """
    Revokes the provided refresh token so it cannot be used again.
    """
    token_hash = hash_token(payload.refresh_token)
    db_token = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash,
    ).first()
    if db_token:
        db_token.revoked = True
        db.commit()
    return {"status": "ok", "message": "Logged out successfully"}


# ── /mfa ───────────────────────────────────────────────────────────────────────

@router.post("/mfa/verify", response_model=MFAVerifyResponse, status_code=status.HTTP_200_OK)
def verify_admin_mfa(payload: MFAVerifyRequest, db: Session = Depends(get_db)):
    """
    Public endpoint to verify admin 2FA code during login per CONTRACT_NOTES.md §1.
    Exchanges temporary mfa_token and TOTP code for full access & refresh tokens.
    """
    try:
        data = jwt.decode(payload.mfa_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = data.get("sub")
        purpose = data.get("purpose")
        if not user_id or purpose != "mfa_pending":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired MFA token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found")

    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not configured for this user")

    if not verify_totp_code(user.mfa_secret, payload.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="mfa_invalid",
        )

    # Valid code: mark mfa_enabled = True
    if not user.mfa_enabled:
        user.mfa_enabled = True
        db.commit()

    # Log admin login action in audit log
    from admin.audit import log_admin_action
    log_admin_action(
        db=db,
        actor_id=user.id,
        actor_email=user.email,
        action="admin.login",
        details={"mfa_verified": True},
    )

    access_token = create_access_token(data={"sub": user.id, "role": user.role})
    refresh_token = _issue_refresh_token(db, user.id)

    return MFAVerifyResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token=access_token,
    )


@router.post("/mfa/setup", response_model=MFASetupResponse, status_code=status.HTTP_200_OK)
def setup_mfa(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve or re-generate admin TOTP provisioning URI.
    """
    if not current_user.mfa_secret:
        current_user.mfa_secret = generate_totp_secret()
        db.commit()
        db.refresh(current_user)

    url = get_otpauth_url(current_user.mfa_secret, current_user.email)
    return MFASetupResponse(
        secret=current_user.mfa_secret,
        otpauth_url=url,
    )

