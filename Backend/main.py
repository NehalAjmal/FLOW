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
app.include_router(auth_router)                                         # /auth/*
app.include_router(session_router,   prefix="/session",   tags=["Session"])
app.include_router(calendar_router,  prefix="/calendar",  tags=["Calendar"])
app.include_router(export_router,    prefix="/export",    tags=["Export"])
app.include_router(user_router,      prefix="/user",      tags=["User"])
app.include_router(team_router,      prefix="/team",      tags=["Team"])
app.include_router(admin_router,     prefix="/admin",     tags=["Admin"])
app.include_router(biometric_router, prefix="/biometric", tags=["Biometric"])
app.include_router(intervention_router, prefix="/intervention", tags=["Intervention"])
app.include_router(breaks_router,                          tags=["Breaks"])     # /breaks, /ratings, /session/{id}/resumption
app.include_router(settings_router,                        tags=["Settings"])

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"status": "FLOW backend running", "version": "2.0", "team": "Error 011"}

@app.get("/api/ping", tags=["Health"])
def ping():
    return {"message": "pong"}