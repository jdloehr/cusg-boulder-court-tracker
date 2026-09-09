"""
Phase 3 appellate supplement (Section 2.3 / 11, expanded on request to also
cover Colorado's own appellate courts): query CourtListener's free search
API for candidate appellate cases -- federal, or Colorado Supreme
Court/Court of Appeals -- for a human (Editor/Contributor) to review and
curate into the public feed as source=federal_courtlistener.

Originally just "federal_supplement" (Section 2.3); generalized when asked
to also surface the Colorado Supreme Court and Court of Appeals. Kept in
one module and one HearingSource value rather than a parallel pipeline,
since the mechanism -- CourtListener search, human judgment, manual
publish with a hand-confirmed date -- is identical for all of them; only
the `court` parameter changes. See PRESET_COURTS below.

Per Section 2.3 / Section 10 open question #3, relevance isn't a clean
keyword filter -- this module surfaces *candidates* only. Nothing here
auto-publishes to the public Hearing list; see app/routers/admin.py's
review endpoints.

Endpoint notes from live testing during build (see
docs/DATA_SOURCE_FINDINGS.md):
- /search/?type=o (opinions) and /search/?type=oa (oral argument audio) work
  with no API token.
- /dockets/ (RECAP docket-level data, which is what would carry a *future*
  scheduled hearing date) returned 401 without a token. CourtListener issues
  free API tokens to registered accounts; set COURTLISTENER_API_TOKEN to
  enable docket-level queries once the team has one.
- Requests without a browser-like User-Agent were blocked (403); this
  module always sends one.
- Colorado's two appellate courts (CourtListener ids "colo" and
  "coloctapp", confirmed live) have real, current opinion data
  (has_opinion_scraper=True for both) but, like federal RECAP,
  no oral-argument scheduling data at all (has_oral_argument_scraper=False
  for both). Colorado publishes its own oral-argument calendars, but only
  as PDFs (coloradojudicial.gov/supreme-court/supreme-court-oral-arguments
  and .../topic/77/court-appeals-oral-arguments), not a structured feed --
  a curator reads the real PDF to get the actual date, same as the Suncor
  SCOTUS example.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import COURTLISTENER_API_BASE, COURTLISTENER_API_TOKEN
from app.db import SessionLocal
from app.models import NewsMention

logger = logging.getLogger(__name__)

# Quick-pick options for the admin UI -- CourtListener court-id -> label.
# Not exhaustive (the search box also takes a free-text court id for any of
# CourtListener's ~3,300 other courts) -- just the ones actually asked for.
PRESET_COURTS = {
    "": "All courts",
    "scotus": "U.S. Supreme Court",
    "colo": "Colorado Supreme Court",
    "coloctapp": "Colorado Court of Appeals",
    "ca10": "U.S. Court of Appeals, 10th Circuit",
    "cod": "U.S. District Court, Colorado",
}


@dataclass
class AppellateCandidate:
    case_name: str
    court: str
    date_filed: str | None
    docket_number: str | None
    absolute_url: str  # relative path on courtlistener.com
    result_type: str  # "opinion" | "oral_argument"
    already_in_news: bool = False  # see check_news_coverage()


def _headers() -> dict:
    headers = {"User-Agent": "Mozilla/5.0"}
    if COURTLISTENER_API_TOKEN:
        headers["Authorization"] = f"Token {COURTLISTENER_API_TOKEN}"
    return headers


def check_news_coverage(case_name: str) -> bool:
    """"Only pull the ones that are in the news or are likely to be in the
    news" (Section 12 addition): there's no automated scheduling feed for
    Colorado's appellate courts to run the usual news-cross-reference
    pipeline against (see module docstring), so this instead checks
    candidates *against* news already gathered by the real
    jobs/news_monitor.py pipeline -- a rough but real signal a curator can
    use to prioritize which candidates are worth the manual work of
    tracking down a real date, rather than a hard filter that could hide a
    genuinely newsworthy case over a name-matching quirk."""
    if not case_name:
        return False
    # Match on the first two "significant" words of the case name (usually
    # a party name) against recent headlines -- simple, and good enough for
    # a "worth a second look" hint rather than a precise match.
    words = [w for w in case_name.replace(",", "").split() if len(w) > 3][:2]
    if not words:
        return False
    db = SessionLocal()
    try:
        query = db.query(NewsMention)
        for word in words:
            query = query.filter(NewsMention.headline.ilike(f"%{word}%"))
        return query.first() is not None
    finally:
        db.close()


def search_candidates(query: str, court: str | None = None, result_type: str = "o",
                       limit: int = 10) -> list[AppellateCandidate]:
    """result_type: "o" = opinions, "oa" = oral argument audio, "r" = RECAP
    filings (requires COURTLISTENER_API_TOKEN)."""
    params = {"q": query, "type": result_type}
    if court:
        params["court"] = court

    resp = httpx.get(f"{COURTLISTENER_API_BASE}/search/", params=params,
                      headers=_headers(), timeout=20)
    resp.raise_for_status()
    data = resp.json()

    candidates = []
    for r in data.get("results", [])[:limit]:
        case_name = r.get("caseName") or r.get("case_name") or "(unnamed)"
        candidates.append(AppellateCandidate(
            case_name=case_name,
            court=r.get("court") or "",
            date_filed=r.get("dateFiled") or r.get("dateArgued"),
            docket_number=r.get("docketNumber"),
            absolute_url=f"https://www.courtlistener.com{r.get('absolute_url', '')}",
            result_type="oral_argument" if result_type == "oa" else "opinion",
            already_in_news=check_news_coverage(case_name),
        ))
    return candidates
