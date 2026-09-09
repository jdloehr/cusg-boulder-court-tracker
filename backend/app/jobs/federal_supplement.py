"""
Phase 3 federal supplement (Section 2.3 / 11): query CourtListener's free
search API for candidate federal cases, for a human (Editor/Contributor) to
review and curate into the public feed as source=federal_courtlistener.

Per Section 2.3 / Section 10 open question #3, federal relevance isn't a
clean keyword filter -- this module surfaces *candidates* only. Nothing
here auto-publishes to the public Hearing list; see
app/routers/admin.py's federal-candidate review endpoints.

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
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import COURTLISTENER_API_BASE, COURTLISTENER_API_TOKEN

logger = logging.getLogger(__name__)


@dataclass
class FederalCandidate:
    case_name: str
    court: str
    date_filed: str | None
    docket_number: str | None
    absolute_url: str  # relative path on courtlistener.com
    result_type: str  # "opinion" | "oral_argument"


def _headers() -> dict:
    headers = {"User-Agent": "Mozilla/5.0"}
    if COURTLISTENER_API_TOKEN:
        headers["Authorization"] = f"Token {COURTLISTENER_API_TOKEN}"
    return headers


def search_candidates(query: str, court: str | None = None, result_type: str = "o",
                       limit: int = 10) -> list[FederalCandidate]:
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
        candidates.append(FederalCandidate(
            case_name=r.get("caseName") or r.get("case_name") or "(unnamed)",
            court=r.get("court") or "",
            date_filed=r.get("dateFiled") or r.get("dateArgued"),
            docket_number=r.get("docketNumber"),
            absolute_url=f"https://www.courtlistener.com{r.get('absolute_url', '')}",
            result_type="oral_argument" if result_type == "oa" else "opinion",
        ))
    return candidates
