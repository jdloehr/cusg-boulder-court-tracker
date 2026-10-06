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
# future custom domain) can be set without a code change.
#
# Oct 2026 review item 12: the default used to always include the two
# localhost dev ports, even in production -- harmless in the sense that
# nothing on the public internet is actually listening there, but still
# a wider allow-list than production needs, and a mismatch with the
# "closed allow-list" the comment above already promises. The default
# now drops them whenever ENVIRONMENT=production; an explicit
# ALLOWED_ORIGINS env var always wins regardless of ENVIRONMENT, same as
# before.
_ALLOWED_ORIGINS_PROD_DEFAULT = "https://cusg-boulder-court-tracker.vercel.app"
_ALLOWED_ORIGINS_DEV_DEFAULT = _ALLOWED_ORIGINS_PROD_DEFAULT + ",http://localhost:5173,http://localhost:3000"
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS",
        _ALLOWED_ORIGINS_PROD_DEFAULT if ENVIRONMENT == "production" else _ALLOWED_ORIGINS_DEV_DEFAULT,
    ).split(",") if o.strip()
]

# Oct 2026 review item 3: app.rate_limit.client_ip trusted the *first*
# X-Forwarded-For entry, which is entirely client-controlled -- anyone
# can send `X-Forwarded-For: 1.2.3.4` themselves and every rate limit
# keyed on IP (login, subscribe, refresh, ...) would key off that fake
# value instead of their real address, making every per-IP limit
# trivially bypassable by rotating a fake value per request. Render
# sits exactly one real proxy hop in front of this app and appends the
# real client IP as the *last* entry (see client_ip's own docstring for
# the full reasoning) -- configurable here in case a future deployment
# adds another trusted hop (a CDN in front of Render, say) without a
# code change.
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))

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

# --- News search (Phase 8 doc: news tracking system rebuild) ----------------
# Replaces the old Section 2.2 multi-feed-polling design: instead of
# scanning several news sites and guessing which article belongs to which
# case, this actively searches for news about each specific upcoming
# hearing (known case number + party names already confirmed by the
# docket) via Google's Custom Search JSON API -- see app/jobs/news_search.py.
# Checked live during build: the 20th Judicial District DA's office has no
# usable press-release feed (a manually-maintained static-PDF archive
# page, most recent visible release from Jan 2025, no RSS) -- so there's
# no separate DA-specific polling source; a DA-announced case is just
# whatever the per-hearing search happens to find, tagged
# SourceType.da_press_release post-hoc when the result URL is on
# bouldercounty.gov.
SEARCH_API_KEY = os.environ.get("SEARCH_API_KEY", "")
SEARCH_ENGINE_ID = os.environ.get("SEARCH_ENGINE_ID", "")
# Google Custom Search JSON API's real free-tier ceiling. At this
# project's actual scale (a handful of eligible hearings, searched once or
# twice each) real usage is expected in the 10-60/day range.
SEARCH_API_DAILY_QUOTA = int(os.environ.get("SEARCH_API_DAILY_QUOTA", "100"))
# When today's query_count reaches this, alert_quota_warning() fires once
# (see app/external_api_usage.py) -- comfortably before the real ceiling,
# so there's still headroom left to actually look into it.
SEARCH_API_ALERT_THRESHOLD = int(os.environ.get("SEARCH_API_ALERT_THRESHOLD", "90"))
# How many days before a hearing's own date the second ("pre-hearing")
# search pass runs, for hearings that still have nothing resolved from
# the first pass -- see app/jobs/news_search.py's cadence logic.
NEWS_SEARCH_PREHEARING_WINDOW_DAYS = int(os.environ.get("NEWS_SEARCH_PREHEARING_WINDOW_DAYS", "5"))

# --- CourtListener federal supplement (Section 2.3) -------------------------
COURTLISTENER_API_BASE = "https://www.courtlistener.com/api/rest/v4"
# Free-tier search/opinion/oral-argument endpoints work without a token.
# Docket/RECAP-level endpoints require a free CourtListener account token --
# set this to enable those. Optional.
COURTLISTENER_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN")

# --- Auth (admin/curation tool, Section 5.4) --------------------------------
_JWT_SECRET_DEV_DEFAULT = "dev-only-secret-change-me"
JWT_SECRET = os.environ.get("JWT_SECRET", _JWT_SECRET_DEV_DEFAULT)
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

# --- Failure alerting (Section 8; upgraded to real email by the Phase 8
# news-search rebuild) ---------------------------------------------------
# "console" (default, safe for local dev with no email configured) logs
# loudly. "email" reuses the existing, already-working
# app/jobs/digest.py::send_email() (SendGrid) to actually deliver the
# alert to ALERT_EMAIL_ADDRESS -- set both in production so a search-API
# quota warning or a job failure actually reaches someone instead of
# sitting in a log nobody's watching.
ALERT_BACKEND = os.environ.get("ALERT_BACKEND", "console")
ALERT_EMAIL_ADDRESS = os.environ.get("ALERT_EMAIL_ADDRESS", "")

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

# --- Calendar-sync doc: Google Calendar OAuth (freebusy-only) ---------------
# A real Google Cloud OAuth application -- client ID/secret and the
# authorized redirect URI must be created there first; this app can't
# generate them. GOOGLE_CALENDAR_REDIRECT_URI must exactly match what's
# registered in that OAuth app's config (Google rejects a mismatch).
GOOGLE_CALENDAR_CLIENT_ID = os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "")
GOOGLE_CALENDAR_CLIENT_SECRET = os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", "")
GOOGLE_CALENDAR_REDIRECT_URI = os.environ.get("GOOGLE_CALENDAR_REDIRECT_URI", "")
# A real Fernet key (Fernet.generate_key()), not a passphrase -- backs
# app/token_encryption.py. This dev-only default only works locally;
# losing/rotating the real one in production makes every stored refresh
# token unrecoverable (same operational posture as rotating JWT_SECRET
# logging everyone out -- Justices would just need to reconnect).
_GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY_DEV_DEFAULT = "4K8kFhq4iUUuPk8dQyjDqCB2sImPLnbtJO0teM_6XJ0="
GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY = os.environ.get(
    "GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY", _GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY_DEV_DEFAULT
)
# How far ahead the sync job pulls real freebusy data -- "the current
# docket window is enough, no need to pull a year of history" (the doc's
# own words). Matches DOCKET_PULL_WINDOW_DAYS above exactly.
GOOGLE_CALENDAR_SYNC_WINDOW_DAYS = int(os.environ.get("GOOGLE_CALENDAR_SYNC_WINDOW_DAYS", str(DOCKET_PULL_WINDOW_DAYS)))

# --- Oct 2026 review item 8: refuse to boot on an insecure production -------
# default. Both placeholders above are public (committed to this open
# source tree) -- a production deployment that forgot to override
# either one would otherwise run indefinitely with a JWT_SECRET anyone
# could forge a valid admin token against, or a
# GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY anyone could decrypt a stored
# Google refresh token with. Local dev and CI never set
# ENVIRONMENT=production, so this never fires there -- see the human
# checklist in docs/DEPLOYMENT.md for setting the real values in
# Render's Environment tab before this is ever allowed to matter.
if ENVIRONMENT == "production":
    _insecure_defaults = []
    if JWT_SECRET == _JWT_SECRET_DEV_DEFAULT:
        _insecure_defaults.append("JWT_SECRET")
    if GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY == _GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY_DEV_DEFAULT:
        _insecure_defaults.append("GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY")
    if _insecure_defaults:
        raise RuntimeError(
            f"ENVIRONMENT=production but {' and '.join(_insecure_defaults)} still "
            f"equal{'s' if len(_insecure_defaults) == 1 else ''} its committed placeholder default. "
            "Set a real value in Render's Environment tab before deploying -- see docs/DEPLOYMENT.md."
        )
