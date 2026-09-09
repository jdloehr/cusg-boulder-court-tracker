from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import admin, justices, public

app = FastAPI(title="CUSG Boulder Court Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # public read API; tighten for the admin origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(admin.router)
app.include_router(justices.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    # Scheduler is opt-in (ENABLE_SCHEDULER=1) rather than automatic: this
    # local dev setup shouldn't be hitting live external sites on every
    # `uvicorn --reload` restart. Turn it on for a real deployment (or run
    # the scripts/run_*.py entrypoints on your host's own cron/scheduled-
    # function feature instead -- see docs/ARCHITECTURE.md).
    if os.environ.get("ENABLE_SCHEDULER") == "1":
        from app.jobs.scheduler import start_scheduler
        start_scheduler()


@app.get("/api/health")
def health():
    return {"status": "ok"}
