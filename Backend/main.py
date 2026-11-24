from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.router     import router as auth_router
from sessions.router import router as session_router
from calendar_app.router import router as calendar_router
from export.router   import router as export_router
from user.router     import router as user_router
from team.router     import router as team_router
from admin.router    import router as admin_router
from biometric.router import router as biometric_router
from settings_app.router import router as settings_router
from interventions.router import router as intervention_router
from breaks_app.router import router as breaks_router
from privacy.router import router as privacy_router
from consent.router  import router as consent_router
from history.router import router as history_router
from schedules.router import router as schedules_router

app = FastAPI(
    title="FLOW API",
    description="AI-Powered Cognitive Alignment System — Team Error 011 — Hacknovate 7.0",
    version="2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
# The Flutter app puts /api/v1 in front of every path (frontend/CONTRACT_NOTES.md),
# while the local agent and older code call the bare paths. So every router is
# mounted twice: at "/x" and at "/api/v1/x". The second copy is hidden from /docs.
API_PREFIXES = ["", "/api/v1"]


def mount(router, prefix: str = "", **kwargs):
    for base in API_PREFIXES:
        app.include_router(router, prefix=base + prefix, include_in_schema=(base == ""), **kwargs)


mount(auth_router)                                                   # /auth/*
mount(session_router,      prefix="/session",      tags=["Session"])
mount(calendar_router,     prefix="/calendar",     tags=["Calendar"])
mount(export_router,       prefix="/export",       tags=["Export"])
mount(user_router,         prefix="/user",         tags=["User"])
mount(team_router,         prefix="/team",         tags=["Team"])
mount(admin_router,        prefix="/admin",        tags=["Admin"])
mount(biometric_router,    prefix="/biometric",    tags=["Biometric"])
mount(intervention_router, prefix="/intervention", tags=["Intervention"])
mount(consent_router,      prefix="/consent",      tags=["Consent"])
mount(breaks_router,       tags=["Breaks"])      # /breaks, /ratings, /session/{id}/resumption
mount(privacy_router,      tags=["Privacy"])     # /me/data-summary, /me/data-export, DELETE /me
mount(settings_router,     tags=["Settings"])    # /pause, /settings
mount(history_router,      tags=["History"])     # /sessions, /session/{id}/replay
mount(schedules_router,    tags=["Schedules"])   # /user/schedules

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"status": "FLOW backend running", "version": "2.0", "team": "Error 011"}

@app.get("/api/ping", tags=["Health"])
def ping():
    return {"message": "pong"}