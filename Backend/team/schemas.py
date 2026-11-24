from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class EmployeeStatus(BaseModel):
    id: str
    display_name: str
    current_status: str  # "In Flow", "Break", "Offline"
    focus_score: int
    burnout_risk: str    # "Low", "Medium", "High"


class TeamMetrics(BaseModel):
    average_focus: int
    trend: List[Dict[str, Any]] = []
    active_sessions_count: int = 0
    total_employees: int = 0


class TeamSummaryResponse(BaseModel):
    # CONTRACT_NOTES §7 wrapper:
    group_size: int = 0
    suppressed: bool = False
    reason: Optional[str] = None
    metrics: Optional[TeamMetrics] = None

    # Legacy fields alongside for backwards compatibility:
    team_name: Optional[str] = None
    average_focus_score: Optional[int] = 0
    active_sessions_count: Optional[int] = 0
    total_employees: Optional[int] = 0
    employees: List[EmployeeStatus] = []
