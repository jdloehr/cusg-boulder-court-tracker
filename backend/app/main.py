from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS, ENVIRONMENT
from app.db import init_db
from app.routers import account, admin, archive, justices, public, reports
from app.security_headers import SecurityHeadersMiddleware

# Real bug, found while debugging a live production issue: every
# app.jobs.digest.send_email() call, every app.account_email_updates.py
# log line, every logging.getLogger(__name__).info(...) anywhere in this
# codebase was silently going nowhere. Uvicorn configures handlers for
# its own named loggers ("uvicorn", "uvicorn.access", "uvicorn.error")
# but never touches the root logger, so any other logger in the process
# has no handler at all and its INFO-level messages are dropped before
# they'd even reach one -- invisible in Render's log stream, invisible
# locally, invisible everywhere. force=True guarantees this actually
# takes effect regardless of whether Uvicorn's own logging setup already
# ran first (it usually has, by the time this module is imported).
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s", force=True)

# Phase-4 doc, Section 2.1/2.7: interactive API docs are a real, if minor,
# attack-surface/probing target once this is linked from an official CUSG
# page, and serve no purpose for an API with no external integrators --
# off in production, still on for local dev.
_docs_kwargs = (
    {"docs_url": None, "redoc_url": None, "openapi_url": None}
    if ENVIRONMENT == "production" else {}
)
app = FastAPI(title="CUSG Boulder Court Tracker API", **_docs_kwargs)

# Security headers on every response (added before CORS so CORS's own
# preflight/actual-request headers still get layered on top correctly by
# Starlette's middleware ordering).
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    # A real, closed allow-list (this app's own frontend + local dev)
    # instead of "*" -- see ALLOWED_ORIGINS in app/config.py. This was a
    # known, flagged gap ("tighten... in production") since Phase 1;
    # Phase 4's security-hardening pass is what actually closes it.
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(admin.router)
app.include_router(justices.router)
app.include_router(archive.router)
app.include_router(account.router)
app.include_router(reports.router)


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
