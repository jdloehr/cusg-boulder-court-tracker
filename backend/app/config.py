"""
Central configuration, read from environment variables with sane local-dev
defaults. Nothing here should need code changes to move from local SQLite to
a hosted Postgres instance -- just set DATABASE_URL.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Environment / CORS (Phase-4 doc, Section 2.1) ---------------------------
# "production" disables the interactive API docs (app/main.py) and is
# meant to be set explicitly on the real deployment (Render) -- defaults
# to "development" so nothing changes for local `uvicorn --reload` use.
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
# Real, closed allow-list instead of "*" -- this API only has one real
# frontend client. Comma-separated env var so the actual Vercel URL (or a
# future custom domain) can be set without a code change; the defaults
# cover this project's known production frontend plus local dev.
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://cusg-boulder-court-tracker.vercel.app,http://localhost:5173,http://localhost:3000",
    ).split(",") if o.strip()
]

# --- Database ---------------------------------------------------------------
# Local dev/demo default: file-based SQLite so this runs with zero external
# services. Production: set DATABASE_URL to a postgresql+psycopg2:// DSN.
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'court_tracker.db'}")

# --- Colorado Judicial Branch docket export (Section 2.1) -------------------
DOCKET_EXPORT_URL = os.environ.get(
    "DOCKET_EXPORT_URL", "https://www.coloradojudicial.gov/dockets/export"
)

# Court location codes as courtLocations[N] query params -- these scope
# WHICH locations' hearings the export includes at all. Confirmed live
# against the coloradojudicial.gov/dockets location picker during build
# (see scripts/verify_data_sources.py and docs/DATA_SOURCE_FINDINGS.md
# section 1 for exactly how, and re-run that script periodically since
# Colorado's judicial branch doesn't publish these as a stable API):
#   7  = "Boulder County" (covers both the county-court and combined/
#        district-court dockets held at the Boulder courthouse)
#   87 = "Boulder County Combined Court - Longmont"
# Which specific CourtLocation enum value a given *row* ends up with
# (boulder_county vs. boulder_district vs. longmont_combined) is decided
# separately, per row, from the CSV's own `Location` text column -- see
# map_location_text() in jobs/docket_pull.py. These two codes just need to
# both be present so no in-scope hearing gets left out of the pull.
COURT_LOCATION_CODES = [
    int(c) for c in os.environ.get("COURT_LOCATION_CODES", "7,87").split(",") if c
]

# How many days ahead the docket-pull job requests. Section 5.1 wants a
# default UI window of 1-2 weeks with browsing further out supported, so we
# pull a wider window than the default view shows.
DOCKET_PULL_WINDOW_DAYS = int(os.environ.get("DOCKET_PULL_WINDOW_DAYS", "28"))

# --- News monitoring (Section 2.2) ------------------------------------------
# `boulder_specific=True` sources are Boulder-focused outlets and are the
# priority signal Section 2.2 is actually after ("a case getting real local
# news coverage"); `boulder_specific=False` sources are statewide outlets
# the build prompt also names (Colorado Sun, 9News) that occasionally cover
# a Boulder case but mostly won't -- kept as a lower-priority supplementary
# check, not the primary scan. `type` controls how process_feed() parses
# the source: "rss" for a standard RSS/Atom feed via feedparser, "wp_json"
# for a WordPress REST API posts endpoint (used where a site blocks its own
# RSS feed to automated fetches but its REST API isn't blocked -- see
# Daily Camera below and docs/DATA_SOURCE_FINDINGS.md section 6).
NEWS_SOURCES = [
    {
        "name": "Boulder Reporting Lab",
        "type": "rss",
        "url": "https://boulderreportinglab.org/feed/",
        "boulder_specific": True,
    },
    {
        # Daily Camera is Boulder's actual daily paper and the single most
        # relevant source in this list -- but its main /feed/ and
        # /category/*/feed/ RSS paths return HTTP 403 to automated fetches
        # (bot-mitigation), confirmed during build. Its WordPress REST API
        # is NOT blocked, and category id 41 ("Crime and Public Safety",
        # slug crime-public-safety) is exactly the right section. Found by
        # fetching one real article and reading its
        # <link rel="alternate" type="application/json"> discovery tag,
        # then querying /wp-json/wp/v2/categories for a matching name.
        "name": "Daily Camera",
        "type": "wp_json",
        "url": "https://www.dailycamera.com/wp-json/wp/v2/posts"
               "?categories=41&per_page=20&orderby=date&order=desc",
        "boulder_specific": True,
    },
    {
        # CU Boulder's own student newspaper -- especially relevant for a
        # CUSG-run pre-law tool, and it does cover CU-adjacent court news
        # (e.g. Title IX proceedings, campus-crime cases).
        "name": "CU Independent",
        "type": "rss",
        "url": "https://www.cuindependent.com/feed/",
        "boulder_specific": True,
    },
    {
        "name": "Boulder Weekly",
        "type": "rss",
        "url": "https://boulderweekly.com/feed/",
        "boulder_specific": True,
    },
    {
        "name": "Colorado Sun",
        "type": "rss",
        "url": "https://coloradosun.com/feed/",
        "boulder_specific": False,
    },
    {
        "name": "9News",
        "type": "rss",
        "url": "https://www.9news.com/feeds/syndication/rss/news/local",
        "boulder_specific": False,
    },
    # 20th Judicial District DA's office does not publish RSS or a
    # discoverable REST API; needs a scraper or manual review per Section
    # 10 open question #6. Not implemented in this build.
]
NEWS_SOURCES_DISABLED = set()  # e.g. {"Some Source"} to pause one without deleting its config

# --- CourtListener federal supplement (Section 2.3) -------------------------
COURTLISTENER_API_BASE = "https://www.courtlistener.com/api/rest/v4"
# Free-tier search/opinion/oral-argument endpoints work without a token.
# Docket/RECAP-level endpoints require a free CourtListener account token --
# set this to enable those. Optional.
COURTLISTENER_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN")

# --- Auth (admin/curation tool, Section 5.4) --------------------------------
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

# --- Email (Section 5.3) -----------------------------------------------------
# "console" (default) renders and logs the email instead of sending it --
# see app/jobs/digest.py::send_email. Set EMAIL_BACKEND=sendgrid (plus
# SENDGRID_API_KEY and EMAIL_FROM_ADDRESS below) for real delivery -- see
# docs/DEPLOYMENT.md's "Real email delivery" section for how to get a
# SendGrid account and API key.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "console")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
# Must be a "Single Sender" address verified in the SendGrid dashboard
# (or an address on a verified domain) -- SendGrid rejects a send from
# any address it hasn't verified.
EMAIL_FROM_ADDRESS = os.environ.get("EMAIL_FROM_ADDRESS", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "CUSG Boulder Court Tracker")

# --- Failure alerting (Section 8) -------------------------------------------
# Same situation as email: no paging/notification account exists yet.
# ALERT_BACKEND "console" logs loudly; swap in Slack/email/PagerDuty here.
ALERT_BACKEND = os.environ.get("ALERT_BACKEND", "console")

# --- Manual refresh (Phase-2 doc, Section 1) --------------------------------
# Global, not per-user: one shared cooldown counted from the most recent
# docket_pull JobRun (scheduled or manual), so many visitors clicking
# refresh in quick succession can't hammer coloradojudicial.gov. The doc's
# own open question #3 suggests 15-30 minutes as a starting point;
# defaulted to the middle of that range.
REFRESH_COOLDOWN_MINUTES = int(os.environ.get("REFRESH_COOLDOWN_MINUTES", "20"))

# --- Justice accounts & profiles (Phase-3 doc) -------------------------------
# Absolute base URL of the deployed frontend, used only to build clickable
# links inside emailed invite/reset messages (e.g.
# f"{FRONTEND_URL}/accept-invite/{token}"). Optional/empty in local dev --
# same relative-link convention as the existing digest email's unsubscribe
# links (app/jobs/digest.py) works fine there; a real deployment should set
# this so the emailed (or console-logged, until real email delivery exists)
# link is actually absolute and clickable.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "").rstrip("/")

INVITE_EXPIRE_HOURS = int(os.environ.get("INVITE_EXPIRE_HOURS", "48"))
PASSWORD_RESET_EXPIRE_HOURS = int(os.environ.get("PASSWORD_RESET_EXPIRE_HOURS", "24"))

# One-time Justice login-email updates (e.g. switching a placeholder
# ".local" address to someone's real @colorado.edu one), applied
# automatically at startup -- see app/account_email_updates.py. A JSON
# object as a string: {"old.email@example.com": "new.email@example.com", ...}.
# Deliberately an env var, not a hardcoded mapping in this file: real
# people's real university email addresses shouldn't live in this
# public repository's source or git history, the same reasoning as
# SENDGRID_API_KEY above. Safe to leave set indefinitely -- see that
# module's docstring for why re-running it is a no-op once applied.
JUSTICE_EMAIL_UPDATES = os.environ.get("JUSTICE_EMAIL_UPDATES", "")
