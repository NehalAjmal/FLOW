from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional


class RegisterRequest(BaseModel):
    full_name:    str
    email:        EmailStr
    password:     str
    age:          Optional[int] = None
    sex:          Optional[str] = None
    account_type: str           = "solo"
    company_code: Optional[str] = None

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        allowed = {"solo", "company_employee", "admin"}
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


class RegisterResponse(BaseModel):
    user_id:       str
    token:         str
    access_token:  Optional[str] = None
    refresh_token: Optional[str] = None
    role:          str
    team_id:       Optional[str] = None
    redirect_to:   str


LoginResponse = RegisterResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token:         Optional[str] = None
