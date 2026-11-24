"""
Consent module for FLOW API.
Manages user privacy consent across scopes: behavior, camera, calendar, llm, team_aggregate.
"""
from .service import get_user_consent, set_user_consent, has_consent, CURRENT_POLICY_VERSION, KNOWN_SCOPES

__all__ = [
    "get_user_consent",
    "set_user_consent",
    "has_consent",
    "CURRENT_POLICY_VERSION",
    "KNOWN_SCOPES",
]
