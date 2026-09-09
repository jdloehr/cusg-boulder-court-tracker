"""
Central configuration, read from environment variables with sane local-dev
defaults. Nothing here should need code changes to move from local SQLite to
a hosted Postgres instance -- just set DATABASE_URL.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

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
# No transactional-email account exists for this build. EMAIL_BACKEND
# "console" renders and logs/persists the digest instead of sending it --
# see app/jobs/digest.py. Swap in a real provider's SDK behind the same
# send_email() call when credentials are available.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "console")

# --- Failure alerting (Section 8) -------------------------------------------
# Same situation as email: no paging/notification account exists yet.
# ALERT_BACKEND "console" logs loudly; swap in Slack/email/PagerDuty here.
ALERT_BACKEND = os.environ.get("ALERT_BACKEND", "console")
