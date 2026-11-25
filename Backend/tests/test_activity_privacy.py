import pytest
from agent.categories import categorize_application, normalize_category
from agent.tracker import WindowTracker
from sessions.router import SignalRequest
from sessions.schemas import StuckRequest
from sessions import service
from llm.prompts import stuck_prompt
from test_session_explainability import db, prepare_live, ingest, SESSION_ID
from db_models.session import Session

SECRET = "Confidential document - Visual Studio Code"

@pytest.mark.parametrize("identity,expected", [("Code.exe", "development"), ("chrome.exe", "browser"), ("Spotify", "entertainment"), ("Discord", "communication"), (SECRET, "unknown"), (None, "unknown")])
def test_local_category(identity, expected):
    assert categorize_application(identity) == expected

@pytest.mark.parametrize("value", [SECRET, None, 123, {}, "browser extra"])
def test_allowlist(value):
    assert normalize_category(value) == "unknown"

def test_switches_within_same_category():
    tracker = WindowTracker()
    events = iter([(1, "development"), (2, "development"), (2, "development")])
    tracker._impl = lambda: next(events)
    for _ in range(3):
        tracker.update()
    assert tracker.snapshot_and_reset() == (1, "development")
    assert tracker.snapshot_and_reset() == (0, "development")

@pytest.mark.parametrize("key,value,expected", [("active_window", SECRET, "unknown"), ("app_category", SECRET, "unknown"), ("app_category", "browser", "browser")])
def test_signal_schema(key, value, expected):
    payload = SignalRequest(session_id="s", keystroke_count=1, window_switches=0, idle_seconds=0, mouse_distance_px=0, timestamp="2026-11-25", **{key:value})
    assert payload.app_category == expected
    assert SECRET not in payload.model_dump_json()

def test_stuck_schema_and_prompt():
    payload = StuckRequest(session_id="s", task_declared="coding", difficulty="moderate", stuck_duration_minutes=5, session_duration_minutes=10, active_window=SECRET)
    assert payload.app_category == "unknown"
    assert SECRET not in stuck_prompt("coding", "moderate", 5, SECRET, 10)

def test_fallback_categories():
    assert service.classify_state(20, 2, 0, "entertainment", 10) == "passive"
    assert service.classify_state(20, 2, 0, "browser", 10) == "deep_work"

def test_database_and_live_state_are_sanitized(db, monkeypatch):
    prepare_live(db, monkeypatch)
    live = ingest(db, window=SECRET)
    assert live["app_category"] == "unknown"
    db.expire_all()
    entry = db.get(Session, SESSION_ID).signal_log[-1]
    assert entry["window"] == entry["app_category"] == "unknown"
    assert SECRET not in str(entry)
