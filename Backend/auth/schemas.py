from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List


class RegisterRequest(BaseModel):
    full_name:    str
    email:        EmailStr
    password:     str
    age:          Optional[int] = None
    sex:          Optional[str] = None
    account_type: str           = "solo"
    company_code: Optional[str] = None
    admin_key:    Optional[str] = None

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        allowed = {"solo", "company_employee", "employee", "admin"}
        if v not in allowed:
            raise ValueError(f"account_type must be one of {allowed}")
        return v


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    token:        str
    password:     str
    age:          Optional[int] = None   # collected on register screen
    sex:          Optional[str] = None   # collected on register screen
    account_type: Optional[str] = "solo"
    company_code: Optional[str] = None
    admin_key:    Optional[str] = None


class RegisterResponse(BaseModel):
    user_id:       str
    token:         Optional[str] = None
    access_token:  Optional[str] = None
    refresh_token: Optional[str] = None
    role:          str
    team_id:       Optional[str] = None
    redirect_to:   str           = "/dashboard"


class LoginResponse(BaseModel):
    user_id:         str
    token:           Optional[str] = None
    access_token:    Optional[str] = None
    refresh_token:   Optional[str] = None
    role:            str
    team_id:         Optional[str] = None
    redirect_to:     str           = "/dashboard"
    mfa_required:    bool          = False
    mfa_token:       Optional[str] = None
    consent_missing: List[str]     = []


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token:         Optional[str] = None


class MFAVerifyRequest(BaseModel):
    mfa_token: str
    code:      str


class MFAVerifyResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token:         Optional[str] = None


class MFASetupResponse(BaseModel):
    secret:      str
    otpauth_url: str
