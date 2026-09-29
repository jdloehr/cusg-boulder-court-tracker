"""
Phase 8 doc: news tracking system rebuild. Replaces the old multi-feed-
polling-then-classify approach (app/jobs/news_monitor.py, deleted) with
an inverted one: for each upcoming Jury Trial/Oral Argument hearing
already in the docket (a known case number + party names, already
confirmed ground truth), actively search for news about that specific
case via Google's Custom Search JSON API, rather than scanning a
firehose of random articles and guessing which one matches. Searching
for a known case is a fundamentally easier, higher-precision problem
than classifying an anonymous article -- see docs/ARCHITECTURE.md's
Phase 8 section for the full rationale.

Two tiers, deterministic, no fuzzy scoring:
- Tier 1 (auto_matched): the hearing's own case number appears in a
  result's title/snippet -- unambiguous, no human review needed.
- Tier 2 (in_weekly_reading_list): no case number found, but a search
  result exists -- surfaced for a human to judge relevance during
  existing curation review (app/routers/admin.py's reading-list queue).

Checked live during build: the 20th Judicial District DA's office has no
usable press-release feed (a manually-maintained static-PDF archive
page, no RSS) -- so there's no separate DA-polling source. A DA-sourced
hit is just whatever the per-hearing search happens to find, tagged
SourceType.da_press_release post-hoc from the result's own URL.

Run manually via scripts/run_news_search.py, or on a schedule via the
GitHub Actions cron (.github/workflows/scheduled-jobs.yml) -- same
pattern as docket_pull.py, since Render's free tier can't reliably keep
an in-process scheduler alive.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.alerting import alert_job_failure
from app.case_categories import find_case_numbers_in_text
from app.config import NEWS_SEARCH_PREHEARING_WINDOW_DAYS, SEARCH_API_KEY, SEARCH_ENGINE_ID
from app.external_api_usage import record_usage
from app.models import (
    Hearing,
    HearingStatus,
    HearingTypeCategory,
    JobRun,
    MatchStatus,
    NewsMention,
    SourceType,
)

logger = logging.getLogger(__name__)

JOB_NAME = "news_search"
SEARCH_API_NAME = "google_custom_search"

# Generic institutional/government captions that occasionally appear as a
# "party name" (the docket export's Name field, split by
# docket_pull.py::re_split_parties) -- skipped in favor of a real named
# party, since searching for "STATE OF COLORADO Boulder court" finds
# nothing useful. Checked against real production data during build: the
# overwhelming majority of real party_names lists have exactly one entry
# and it's already a real person's name, so this denylist is a safety
# net for the rare exception, not the common case.
_GENERIC_PARTY_DENYLIST = {
    "STATE OF COLORADO", "THE STATE OF COLORADO", "PEOPLE OF THE STATE OF COLORADO",
    "THE PEOPLE OF THE STATE OF COLORADO", "THE PEOPLE", "PEOPLE",
    "COUNTY OF BOULDER", "CITY OF BOULDER", "BOULDER COUNTY", "IN RE", "IN THE MATTER OF",
}

_RETRY_BACKOFF_SECONDS = (0, 1, 2, 4)  # first attempt has no delay


def _eligible_hearings_base(db: Session):
    """Hearings worth a news search at all -- the same pair of hearing
    types docket_pull.py::should_include_by_default() already treats as
    "the hearings worth surfacing" (minus its juvenile/appearance-type
    legs, which don't bear on whether a search is worth running)."""
    return db.query(Hearing).filter(
        Hearing.hearing_type_category.in_([HearingTypeCategory.jury_trial, HearingTypeCategory.oral_argument_motions]),
        Hearing.status != HearingStatus.cancelled,
        Hearing.is_excluded.is_(False),
    )


def _pass1_initial_candidates(db: Session) -> list[Hearing]:
    """Every eligible hearing that's never had an initial search --
    covers a brand-new hearing the moment docket_pull.py creates it, and
    self-heals on deploy day (every pre-existing eligible hearing gets
    one initial search on this job's first run)."""
    return _eligible_hearings_base(db).filter(Hearing.news_search_initial_at.is_(None)).all()


def _pass2_prehearing_candidates(db: Session, now: datetime) -> list[Hearing]:
    """Eligible hearings within NEWS_SEARCH_PREHEARING_WINDOW_DAYS of
    their own date that still have nothing resolved -- skips any hearing
    whose one NewsMention row already represents a human/system call
    (auto_matched/manually_linked/dismissed); only re-searches a hearing
    with no row at all, or one still sitting at in_weekly_reading_list."""
    window_end = now.date() + timedelta(days=NEWS_SEARCH_PREHEARING_WINDOW_DAYS)
    resolved_hearing_ids = db.query(NewsMention.hearing_id).filter(
        NewsMention.match_status.in_([MatchStatus.auto_matched, MatchStatus.manually_linked, MatchStatus.dismissed])
    )
    return (
        _eligible_hearings_base(db)
        .filter(
            Hearing.news_search_prehearing_at.is_(None),
            Hearing.date >= now.date(),
            Hearing.date <= window_end,
            ~Hearing.id.in_(resolved_hearing_ids),
        )
        .all()
    )


def build_search_query(hearing: Hearing) -> Optional[str]:
    """First usable party name + "Boulder court" -- None (caller logs and
    skips this hearing) if party_names is empty/unparseable or every
    name is denylisted."""
    if not hearing.party_names:
        return None
    try:
        names = json.loads(hearing.party_names)
    except (json.JSONDecodeError, TypeError):
        return None
    for name in names:
        cleaned = (name or "").strip()
        if cleaned and cleaned.upper() not in _GENERIC_PARTY_DENYLIST:
            return f"{cleaned} Boulder court"
    return None


def _normalize_case_number(raw: str) -> str:
    # Same normalization app.case_categories.decode_case_category uses --
    # keeps this comparison consistent with how case numbers are treated
    # everywhere else in this codebase.
    return (raw or "").strip().upper().replace(" ", "").replace("-", "")


def _is_da_source(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    return host == "bouldercounty.gov" or host.endswith(".bouldercounty.gov")


def classify_search_item(item: dict, hearing: Hearing) -> tuple[MatchStatus, SourceType]:
    """item = one Google Custom Search items[] entry (title/snippet/link).
    A case number found in the title+snippet matching this hearing's own
    case number is Tier 1 -- deterministic, no scoring. Anything else is
    Tier 2, a candidate for human review."""
    text = f"{item.get('title', '')} {item.get('snippet', '')}"
    found = [_normalize_case_number(c) for c in find_case_numbers_in_text(text)]
    is_da = _is_da_source(item.get("link", ""))
    if _normalize_case_number(hearing.case_number) in found:
        return MatchStatus.auto_matched, (SourceType.da_press_release if is_da else SourceType.search_result_case_number)
    return MatchStatus.in_weekly_reading_list, (SourceType.da_press_release if is_da else SourceType.search_result_general)


def _call_search_api(query: str, db: Session, now: datetime) -> dict:
    """httpx.get to Google's Custom Search JSON API. Retries transient
    failures (timeout, connection error, 5xx) with a short backoff --
    NOT retried for 429 (quota exhausted; retrying just spends more of
    the remaining daily budget for nothing) or 400 (a bad request/
    misconfiguration, not transient). Records one usage tally per actual
    outbound attempt, including retries, since Google counts each one
    against the quota regardless of outcome."""
    last_exc: Optional[Exception] = None
    for delay in _RETRY_BACKOFF_SECONDS:
        if delay:
            time.sleep(delay)
        record_usage(db, SEARCH_API_NAME, now)
        try:
            resp = httpx.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": SEARCH_API_KEY, "cx": SEARCH_ENGINE_ID, "q": query, "num": 10},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            continue
        if resp.status_code == 429:
            raise RuntimeError(f"Search API quota exhausted: {resp.text}")
        if resp.status_code == 400:
            raise RuntimeError(f"Search API rejected the request (query={query!r}): {resp.text}")
        if resp.status_code >= 500:
            last_exc = RuntimeError(f"Search API server error {resp.status_code}: {resp.text}")
            continue
        resp.raise_for_status()
        return resp.json()
    raise last_exc or RuntimeError("Search API call failed with no captured exception")


@dataclass
class SearchOutcome:
    """What happened for one hearing this run -- distinguishes a genuine
    failure (don't stamp the cadence timestamp, so it's retried next run)
    from every other outcome (do stamp it -- "we searched and found
    nothing" is still a completed attempt, not a failure)."""
    status: str  # "skipped_resolved" | "no_query" | "no_results" | "tier1" | "tier2" | "error"
    error: Optional[str] = None


def search_for_hearing(db: Session, hearing: Hearing, now: datetime) -> SearchOutcome:
    """The whole per-hearing pipeline. Never raises -- any exception is
    caught, logged, and returned as a SearchOutcome(status="error"), so
    one hearing's failure can't kill run_news_search()'s loop over every
    other hearing (Section 4's per-hearing isolation requirement)."""
    try:
        existing = db.query(NewsMention).filter(NewsMention.hearing_id == hearing.id).first()
        if existing and existing.match_status in (
            MatchStatus.auto_matched, MatchStatus.manually_linked, MatchStatus.dismissed,
        ):
            return SearchOutcome(status="skipped_resolved")

        query = build_search_query(hearing)
        if query is None:
            logger.info("news_search: hearing %s has no usable party name, skipping", hearing.case_number)
            return SearchOutcome(status="no_query")

        data = _call_search_api(query, db, now)
        items = data.get("items", [])  # Google omits "items" entirely on zero results, not an error
        if not items:
            logger.info("news_search: hearing %s -- 0 results for query %r", hearing.case_number, query)
            return SearchOutcome(status="no_results")

        # First case-number match wins outright (Tier 1); otherwise the
        # doc's "collapse into ONE entry" ask means keeping only the
        # single best candidate, not every item -- the first result
        # Google itself ranked highest.
        chosen_item, chosen_status, chosen_source_type = None, None, None
        for item in items:
            status, source_type = classify_search_item(item, hearing)
            if status == MatchStatus.auto_matched:
                chosen_item, chosen_status, chosen_source_type = item, status, source_type
                break
        if chosen_item is None:
            chosen_item = items[0]
            chosen_status, chosen_source_type = classify_search_item(chosen_item, hearing)

        link = chosen_item.get("link", "")
        headline = (chosen_item.get("title") or "")[:500]
        source_name = urlparse(link).netloc or "Unknown"

        if existing:
            # existing.match_status must be in_weekly_reading_list here
            # (the only state the resolved-status check above lets
            # through) -- update it in place rather than creating a
            # second row for the same hearing.
            existing.article_url = link
            existing.source_name = source_name
            existing.headline = headline
            existing.source_type = chosen_source_type
            existing.match_status = chosen_status
            existing.fetched_at = now
        else:
            db.add(NewsMention(
                hearing_id=hearing.id, article_url=link, source_name=source_name, headline=headline,
                source_type=chosen_source_type, match_status=chosen_status, fetched_at=now,
            ))

        tier = "tier1" if chosen_status == MatchStatus.auto_matched else "tier2"
        logger.info("news_search: hearing %s -> %s (%s)", hearing.case_number, chosen_status.value, chosen_source_type.value)
        return SearchOutcome(status=tier)
    except Exception as exc:  # noqa: BLE001 -- per-hearing isolation, see docstring
        logger.warning("news_search: search failed for hearing %s: %s", hearing.case_number, exc)
        return SearchOutcome(status="error", error=str(exc))


def run_news_search(db: Session, now: datetime | None = None) -> JobRun:
    now = now or datetime.utcnow()
    job_run = JobRun(job_name=JOB_NAME, started_at=now)
    db.add(job_run)
    db.flush()

    try:
        pass1 = _pass1_initial_candidates(db)
        pass2 = _pass2_prehearing_candidates(db, now)

        # A hearing eligible for both passes on the same day is searched
        # exactly once; both timestamps get stamped on a clean outcome.
        passes_by_hearing: dict[str, set[str]] = {}
        hearings_by_id: dict[str, Hearing] = {}
        for h in pass1:
            passes_by_hearing.setdefault(h.id, set()).add("initial")
            hearings_by_id[h.id] = h
        for h in pass2:
            passes_by_hearing.setdefault(h.id, set()).add("prehearing")
            hearings_by_id[h.id] = h

        checked = tier1 = tier2 = errors = 0
        for hearing_id, passes in passes_by_hearing.items():
            hearing = hearings_by_id[hearing_id]
            checked += 1
            outcome = search_for_hearing(db, hearing, now)
            if outcome.status == "error":
                errors += 1
                continue
            if outcome.status == "tier1":
                tier1 += 1
            elif outcome.status == "tier2":
                tier2 += 1
            if "initial" in passes:
                hearing.news_search_initial_at = now
            if "prehearing" in passes:
                hearing.news_search_prehearing_at = now

        job_run.rows_seen = checked
        job_run.rows_upserted = tier1 + tier2
        job_run.success = True
        job_run.finished_at = datetime.utcnow()
        db.commit()

        logger.info(
            "news_search: %d hearings checked, %d Tier 1 auto-matches, %d Tier 2 reading-list items, %d errors",
            checked, tier1, tier2, errors,
        )
        # Section 4: low-urgency, not page-the-team -- this pipeline
        # enriches the docket feed, it isn't the site's backbone.
        if checked > 0 and errors == checked:
            alert_job_failure(JOB_NAME, f"All {checked} hearing searches failed this run", severity="low")

        return job_run
    except Exception as exc:  # noqa: BLE001 - job boundary, mirrors docket_pull.py's pattern
        db.rollback()
        job_run.success = False
        job_run.error_message = str(exc)
        job_run.finished_at = datetime.utcnow()
        db.add(job_run)
        db.commit()
        alert_job_failure(JOB_NAME, str(exc), severity="low")
        raise
