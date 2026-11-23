from datetime import datetime, timedelta, timezone

from interventions.gating import check_gate, in_quiet_hours

# 2026-11-24 10:00 UTC = 15:30 in India (Asia/Kolkata)
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


def test_allowed_when_nothing_blocks():
    assert check_gate(NOW).allowed


def test_paused():
    r = check_gate(NOW, paused_until=NOW + timedelta(minutes=30))
    assert (r.allowed, r.reason) == (False, "paused")


def test_pause_has_expired():
    assert check_gate(NOW, paused_until=NOW - timedelta(minutes=1)).allowed


def test_in_meeting():
    assert check_gate(NOW, in_meeting=True).reason == "in_meeting"


def test_on_break():
    assert check_gate(NOW, on_break=True).reason == "on_break"


def test_14_minutes_after_last_prompt_is_too_soon():
    r = check_gate(NOW, last_prompt_at=NOW - timedelta(minutes=14))
    assert r.reason == "too_soon"


def test_15_minutes_after_last_prompt_is_fine():
    assert check_gate(NOW, last_prompt_at=NOW - timedelta(minutes=15)).allowed


def test_quiet_hours_use_the_users_time_zone():
    # 15:30 in India falls inside 15:00-16:00, but 10:00 UTC does not.
    assert in_quiet_hours(NOW, ("15:00", "16:00"), "Asia/Kolkata")
    assert not in_quiet_hours(NOW, ("15:00", "16:00"), "UTC")


def test_quiet_hours_across_midnight():
    late = datetime(2026, 11, 24, 17, 0, tzinfo=timezone.utc)    # 22:30 India
    early = datetime(2026, 11, 24, 0, 30, tzinfo=timezone.utc)   # 06:00 India
    day = datetime(2026, 11, 24, 6, 30, tzinfo=timezone.utc)     # 12:00 India
    window = ("22:00", "07:00")
    assert in_quiet_hours(late, window, "Asia/Kolkata")
    assert in_quiet_hours(early, window, "Asia/Kolkata")
    assert not in_quiet_hours(day, window, "Asia/Kolkata")


def test_no_quiet_hours_set():
    assert not in_quiet_hours(NOW, None, "Asia/Kolkata")


def test_first_blocking_rule_wins():
    r = check_gate(NOW, paused_until=NOW + timedelta(hours=1), in_meeting=True)
    assert r.reason == "paused"
