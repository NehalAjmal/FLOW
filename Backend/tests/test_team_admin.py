# Task 6: team page endpoints (members, invites, privacy status, team averages).
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_models  # noqa: registers every table
from db_models.audit_log import AuditLog
from db_models.base import Base, get_db
from db_models.breaks import Break
from db_models.intervention import Intervention
from db_models.invite import Invite
from db_models.session import Session
from db_models.team import Team
from db_models.user import User
from auth.dependencies import get_current_user
from consent.service import has_consent, set_user_consent
from admin import invites as invite_service
from admin.router import router as admin_router
from team import metrics
from team.router import router as team_router

# Tuesday 24 Nov 2026, 10:00 UTC. Viewer's zone is UTC, so the week starts Mon 23 Nov.
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
MONDAY = datetime(2026, 11, 23, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([Team(id="t1", name="Core", company_code="CORE01", admin_key="x"),
                Team(id="t2", name="Other", company_code="OTH001", admin_key="x")])
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add(User(id="boss", full_name="Boss", email="boss@example.com", password_hash="x",
                role="admin", team_id="t1", created_at=old))
    db.add(User(id="boss2", full_name="Other Boss", email="b2@example.com", password_hash="x",
                role="admin", team_id="t2", created_at=old))
    db.commit()
    yield db
    db.close()


def add_member(db, uid, team="t1", consent=True):
    db.add(User(id=uid, full_name=f"Person {uid}", email=f"{uid}@example.com", password_hash="x",
                role="employee", team_id=team, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db.commit()
    if consent:
        set_user_consent(db, uid, "team_aggregate", True)


def add_session(db, sid, uid, start, minutes=60, score=70, ended=True, log=None):
    db.add(Session(id=sid, user_id=uid, start_time=start, focus_score=score,
                   end_time=start + timedelta(minutes=minutes) if ended else None,
                   declared_difficulty="heavy", task_description="SECRET TASK",
                   signal_log=log or []))
    db.commit()


@pytest.fixture
def as_user(db, monkeypatch):
    """Returns a client factory: as_user('boss') acts as that user, at NOW."""
    real_init = metrics.TeamView.__init__

    def fixed_now(self, db_, viewer, now=None):
        real_init(self, db_, viewer, now or NOW)
    monkeypatch.setattr(metrics.TeamView, "__init__", fixed_now)

    def make(uid):
        app = FastAPI()
        app.include_router(admin_router, prefix="/admin")
        app.include_router(team_router, prefix="/team")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: db.get(User, uid)
        return TestClient(app)
    return make


def five_members(db):
    for i in range(5):
        add_member(db, f"m{i}")


# ── who is counted ───────────────────────────────────────

def test_members_only_with_consent_and_own_team(db):
    five_members(db)
    add_member(db, "noconsent", consent=False)
    add_member(db, "elsewhere", team="t2")
    ids = [u.id for u in metrics.members(db, "t1")]
    assert ids == ["m0", "m1", "m2", "m3", "m4"]          # no admin, no un-consented, no other team


def test_suppressed_under_five(db, as_user):
    for i in range(4):
        add_member(db, f"m{i}")
    for path in ["/team/summary", "/admin/summary", "/admin/trend", "/admin/insights",
                 "/admin/strain", "/admin/meeting-window"]:
        r = as_user("boss").get(path).json()
        assert r["suppressed"] is True and r["metrics"] is None and r["group_size"] == 4, path
        assert r["reason"] == "min_group_size_5"


def test_admin_only(db, as_user):
    five_members(db)
    for path in ["/admin/members", "/admin/members/m1", "/admin/privacy-status", "/admin/invites",
                 "/admin/summary"]:
        assert as_user("m0").get(path).status_code == 403, path


# ── /admin/members ───────────────────────────────────────

def test_member_summary(db, as_user):
    five_members(db)
    # Monday: 60 min with a 10 min break; Tuesday: a live session started 30 min ago
    add_session(db, "s1", "m1", MONDAY + timedelta(hours=9))
    db.add(Break(session_id="s1", taken=True, taken_at=MONDAY + timedelta(hours=9, minutes=30),
                 ended_at=MONDAY + timedelta(hours=9, minutes=40)))
    db.add(Intervention(user_id="m1", session_id="s1", kind="fatigue", response="accepted",
                        shown_at=MONDAY + timedelta(hours=9, minutes=29)))
    db.add(Intervention(user_id="m1", session_id="s1", kind="distracted", response="overridden",
                        shown_at=MONDAY + timedelta(hours=9, minutes=10)))
    add_session(db, "s2", "m1", NOW - timedelta(minutes=30), ended=False, score=None)
    add_session(db, "last", "m1", MONDAY - timedelta(days=3), minutes=45)   # previous week
    db.commit()

    items = as_user("boss").get("/admin/members").json()["items"]
    assert [m["id"] for m in items] == ["m0", "m1", "m2", "m3", "m4"]
    m1 = items[1]
    assert m1["name"] == "Person m1"
    assert m1["focus_by_day"] == [50, 30, 0, 0, 0, 0, 0]
    assert m1["sessions"] == 2
    assert m1["breaks_taken"] == 1 and m1["breaks_suggested"] == 1
    assert m1["nudges"] == {"taken": 1, "snoozed": 0, "dismissed": 1}
    assert m1["in_session"] is True
    assert m1["prev_focus_minutes"] == 45
    assert m1["strain"] == "low"
    assert "SECRET" not in str(items) and "task" not in str(items)


def test_member_detail_and_audit(db, as_user):
    five_members(db)
    log = [{"at": (MONDAY + timedelta(hours=9, minutes=m)).isoformat(), "score": 30} for m in range(10)]
    add_session(db, "s1", "m2", MONDAY + timedelta(hours=9), log=log)
    r = as_user("boss").get("/admin/members/m2")
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["strain"] == "high"
    assert len(d["days"]) == 7 and d["days"][0]["date"] == "2026-11-23"
    assert d["days"][0]["sessions"] == [{"start": (MONDAY + timedelta(hours=9)).isoformat(),
                                         "end": (MONDAY + timedelta(hours=10)).isoformat(),
                                         "demand": "heavy"}]
    assert len(d["focus_trend"]) == 30 and d["focus_trend"][-2] == {"date": "2026-11-23", "value": 60}
    assert d["strain_trend"] == [{"date": "2026-11-23", "value": 1.0}]
    assert "SECRET" not in str(d) and "score" not in str(d)

    entry = db.query(AuditLog).filter(AuditLog.action == "member.view").one()
    assert entry.actor_id == "boss" and entry.target_id == "m2"


def test_member_detail_404s(db, as_user):
    five_members(db)
    add_member(db, "noconsent", consent=False)
    add_member(db, "elsewhere", team="t2")
    for mid in ["nobody", "noconsent", "elsewhere", "boss"]:
        assert as_user("boss").get(f"/admin/members/{mid}").status_code == 404, mid
    assert db.query(AuditLog).filter(AuditLog.action == "member.view").count() == 0


def test_revoking_consent_removes_person(db, as_user):
    five_members(db)
    set_user_consent(db, "m3", "team_aggregate", False)
    ids = [m["id"] for m in as_user("boss").get("/admin/members").json()["items"]]
    assert "m3" not in ids


# ── team summary and admin aggregates ────────────────────

def test_team_summary_for_members(db, as_user):
    five_members(db)
    for i in range(5):
        add_session(db, f"s{i}", f"m{i}", MONDAY + timedelta(hours=10), score=60 + i * 5)
    r = as_user("m0").get("/team/summary").json()          # employees can see it too
    assert r["suppressed"] is False and r["group_size"] == 5 and r["team_name"] == "Core"
    m = r["metrics"]
    assert m["average_focus"] == 0.7
    assert m["trend"] == [{"date": "2026-11-23", "value": 0.7}]
    assert m["focus_minutes_per_day"] == 60 and m["sessions_per_day"] == 1.0
    assert m["focus_minutes_this_week"] == 60
    assert m["break_uptake"] is None                      # nobody was offered a break
    assert m["peak_hours"] == []                          # 5 sessions isn't enough to say
    assert "employees" not in r                           # teammates never see a person


def test_meeting_window_and_peaks_from_data(db, as_user):
    five_members(db)
    # Everyone focuses 09:00-12:00 and 13:00-17:00 on Mon 16 and Tue 17 Nov; 12:00-13:00 is free.
    n = 0
    for day in (16, 17):
        for i in range(5):
            base = datetime(2026, 11, day, tzinfo=timezone.utc)
            add_session(db, f"a{n}", f"m{i}", base + timedelta(hours=9), minutes=180)
            add_session(db, f"b{n}", f"m{i}", base + timedelta(hours=13), minutes=240)
            n += 1
    boss = as_user("boss")
    assert boss.get("/admin/meeting-window").json()["metrics"] == {"start": "12:00", "end": "13:00"}
    assert boss.get("/admin/insights").json()["metrics"]["peak_hours"] == [9, 10, 11]


def test_meeting_window_null_without_data(db, as_user):
    five_members(db)
    r = as_user("boss").get("/admin/meeting-window").json()
    assert r["suppressed"] is False and r["metrics"] is None   # no made-up window


def test_strain_note(db, as_user):
    five_members(db)
    add_session(db, "s1", "m1", NOW - timedelta(days=10))
    add_session(db, "s2", "m1", NOW - timedelta(days=1))
    for k in range(2):
        db.add(Intervention(user_id="m1", session_id="s1", kind="fatigue", shown_at=NOW - timedelta(days=10)))
    for k in range(3):
        db.add(Intervention(user_id="m1", session_id="s2", kind="trough", shown_at=NOW - timedelta(days=1)))
    db.commit()
    m = as_user("boss").get("/admin/strain").json()["metrics"]
    assert m == {"level": "low", "note": "Break suggestions up 50% vs last week."}


def test_admin_summary(db, as_user):
    five_members(db)
    add_session(db, "live", "m0", NOW - timedelta(minutes=20), ended=False, score=None)
    add_session(db, "old", "m1", NOW - timedelta(days=2), ended=False, score=None)   # abandoned
    m = as_user("boss").get("/admin/summary").json()["metrics"]
    assert m["active_count"] == 1 and m["session_volume"] == 1


# ── privacy status ───────────────────────────────────────

def test_privacy_status(db, as_user):
    for i in range(3):
        add_member(db, f"m{i}")
    r = as_user("boss").get("/admin/privacy-status").json()
    assert r["group_size"] == 3 and r["suppressed"] is True
    assert "Typing, mouse or camera data" in r["cannot_see"]
    assert "Each person's focus time, sessions and breaks" in r["can_see"]


# ── invites ──────────────────────────────────────────────

def test_invite_create_list_revoke(db, as_user):
    boss = as_user("boss")
    r = boss.post("/admin/invites", json={"valid_for_hours": 48})
    assert r.status_code == 201
    made = r.json()
    assert made["url"].startswith("http://localhost:8080/invite?token=") and made["used"] is False
    token = made["url"].split("token=")[1]
    assert db.query(Invite).one().token_hash != token          # only the hash is stored

    items = boss.get("/admin/invites").json()["items"]
    assert len(items) == 1 and "url" not in items[0]
    assert as_user("boss2").get("/admin/invites").json()["items"] == []        # other team
    assert as_user("boss2").delete(f"/admin/invites/{made['id']}").status_code == 404

    assert boss.delete(f"/admin/invites/{made['id']}").status_code == 204
    assert boss.get("/admin/invites").json()["items"] == []
    actions = [a.action for a in db.query(AuditLog).all()]
    assert actions.count("invite.create") == 1 and actions.count("invite.revoke") == 1


def test_invite_hours_limits(db, as_user):
    boss = as_user("boss")
    assert boss.post("/admin/invites", json={"valid_for_hours": 0}).status_code == 422
    assert boss.post("/admin/invites", json={"valid_for_hours": 24 * 31}).status_code == 422
    assert boss.post("/admin/invites", json={}).status_code == 201             # default 7 days


def test_invite_check(db):
    boss = db.get(User, "boss")
    inv, url = invite_service.create(db, boss, 1, now=NOW)
    token = url.split("token=")[1]
    assert invite_service.check(db, url, now=NOW).id == inv.id                 # whole link works too
    with pytest.raises(invite_service.InviteError, match="expired"):
        invite_service.check(db, token, now=NOW + timedelta(hours=2))
    with pytest.raises(invite_service.InviteError, match="invalid"):
        invite_service.check(db, "nope", now=NOW)
    invite_service.mark_used(db, inv, "boss")
    with pytest.raises(invite_service.InviteError, match="used"):
        invite_service.check(db, token, now=NOW)


def test_register_with_invite(db):
    from auth.router import router as auth_router
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    _, url = invite_service.create(db, db.get(User, "boss"), 24)
    body = {"name": "New Person", "email": "new@example.com", "password": "pw123456",
            "account_type": "employee", "invite_token": url.split("token=")[1]}
    r = c.post("/auth/register", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["team_id"] == "t1" and r.json()["role"] == "employee"
    user = db.query(User).filter(User.email == "new@example.com").one()
    assert user.full_name == "New Person"
    assert has_consent(db, user.id, "team_aggregate")
    assert db.query(Invite).one().used_by == user.id

    again = dict(body, email="other@example.com")
    r = c.post("/auth/register", json=again)
    assert r.status_code == 400 and r.json()["detail"] == "invite_used"


def test_audit_log_only_own_team(db, as_user):
    as_user("boss").post("/admin/invites", json={})
    as_user("boss2").post("/admin/invites", json={})
    items = as_user("boss").get("/admin/audit-log").json()["items"]
    assert len(items) == 1 and items[0]["actor"] == "boss@example.com"
