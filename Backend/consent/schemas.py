from pydantic import BaseModel
from typing import Dict, Optional


class ScopeStatus(BaseModel):
    granted: bool
    version: str
    timestamp: str


class ConsentResponse(BaseModel):
    policy_version: str
    scopes: Dict[str, ScopeStatus]


class UpdateConsentRequest(BaseModel):
    granted: bool
    policy_version: Optional[str] = "1.0"
