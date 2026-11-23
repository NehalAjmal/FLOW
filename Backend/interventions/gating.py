# interventions/gating.py
# Decides whether FLOW is allowed to show a prompt right now.
# Pure logic: no database, no clock. The caller passes everything in,
# which makes every rule easy to test.

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_GAP = timedelta(minutes=15)


@dataclass
class GateResult:
    allowed: bool
    reason: Optional[str] = None   # why it was blocked; None when allowed


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def in_quiet_hours(now_utc: datetime, quiet_hours: Optional[Tuple[str, str]], tz_name: str) -> bool:
    """quiet_hours is ("22:00", "07:00") in the user's own time zone, or None."""
    if not quiet_hours:
        return False
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")

    local = now_utc.astimezone(tz).time()
    start, end = _parse_hhmm(quiet_hours[0]), _parse_hhmm(quiet_hours[1])

    if start == end:            # same start and end = no quiet window
        return False
    if start < end:             # same-day window, e.g. 13:00-14:00
        return start <= local < end
    return local >= start or local < end   # crosses midnight, e.g. 22:00-07:00


def check_gate(
    now_utc: datetime,
    *,
    paused_until: Optional[datetime] = None,
    on_break: bool = False,
    in_meeting: bool = False,
    quiet_hours: Optional[Tuple[str, str]] = None,
    tz_name: str = "UTC",
    last_prompt_at: Optional[datetime] = None,
) -> GateResult:
    """Run every rule in order. The first one that blocks wins."""
    if paused_until is not None and now_utc < paused_until:
        return GateResult(False, "paused")
    if on_break:
        return GateResult(False, "on_break")
    if in_meeting:
        return GateResult(False, "in_meeting")
    if in_quiet_hours(now_utc, quiet_hours, tz_name):
        return GateResult(False, "quiet_hours")
    if last_prompt_at is not None and now_utc - last_prompt_at < MIN_GAP:
        return GateResult(False, "too_soon")
    return GateResult(True)
