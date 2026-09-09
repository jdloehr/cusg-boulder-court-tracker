"""
Phase 2 (Section 2.2 / 11): poll local news RSS feeds, extract case numbers
and candidate party names from each article, and cross-reference against
the Hearing table. A match attaches a NewsMention row (match_status=
auto_matched); no match queues the article for manual curator review
(match_status=unmatched_review) per Section 2.2's "No-match handling".

This is a secondary *enrichment* signal layered on the docket-export
pipeline (jobs/docket_pull.py) -- it never creates Hearing rows itself.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime

import feedparser
import httpx
from sqlalchemy.orm import Session

from app.alerting import alert_job_failure
from app.case_categories import find_case_numbers_in_text
from app.config import NEWS_SOURCES, NEWS_SOURCES_DISABLED
from app.models import Hearing, HearingStatus, JobRun, MatchStatus, NewsMention

logger = logging.getLogger(__name__)

JOB_NAME = "news_monitor"

# Very lightweight proper-noun-run extractor for candidate party names, used
# only as a fallback when no case number is found in the text. Looks for
# runs of 2-3 capitalized words (e.g. "Barry Morphew", "Yvonne Woods") while
# skipping common sentence-initial capitals. This is intentionally simple --
# the spec calls this out as needing human review for anything that doesn't
# cleanly resolve, and this function's whole job is to produce *candidates*
# for that review, not final answers.
#
# Deliberately uses `[ ]+` (literal spaces only), not `\s+`, between the two
# capitalized words: a real live run against Daily Camera surfaced
# "Telluride\nColorado" as a "candidate" because `\s` matches newlines,
# letting the last word of a headline glue onto the first word of the
# summary. That's not a hypothetical -- see
# tests/test_news_monitor.py::test_extract_party_candidates_does_not_cross_line_breaks.
_NAME_RUN_RE = re.compile(r"\b([A-Z][a-z]+(?:[ ]+[A-Z]\.?)?[ ]+[A-Z][a-z]+)\b")
_COMMON_LEADING_WORDS = {"The", "A", "An", "This", "That", "In", "On", "After", "Colorado", "Boulder"}
# Same live run also surfaced "Dolores Peak", "San Miguel", and "County
# Sheriff" as candidates from one plane-crash story -- real two-capitalized-
# word sequences, just place names and institutions, not people. A simple
# denylist, checked against *either* word, catches the common cases without
# trying to build a real named-entity recognizer for what's meant to be a
# lightweight fallback signal.
_NON_NAME_WORDS = {
    "County", "Sheriff", "Office", "Department", "Peak", "Springs", "Mountain",
    "Police", "Court", "District", "City", "Creek", "Valley", "Lake", "River",
    "San", "Fort", "Mount", "Saint", "North", "South", "East", "West",
}


def extract_party_candidates(text: str) -> list[str]:
    candidates = []
    for match in _NAME_RUN_RE.finditer(text or ""):
        name = match.group(1)
        words = name.split()
        if words[0] in _COMMON_LEADING_WORDS or any(w in _NON_NAME_WORDS for w in words):
            continue
        if name not in candidates:
            candidates.append(name)
    return candidates


def fetch_article_text(url: str) -> str | None:
    """Best-effort fetch of the full article body to widen the case-number
    search beyond the RSS summary. Many news sites block non-browser
    fetches on article pages even when their RSS feed is open (observed
    during build -- see docs/DATA_SOURCE_FINDINGS.md), so failures here are
    expected and handled per-article, not fatal to the run."""
    try:
        resp = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        resp.raise_for_status()
        # Strip tags crudely -- good enough for regex scanning, not meant to
        # produce clean readable text.
        return re.sub(r"<[^>]+>", " ", resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not fetch full article text for %s (%s) -- falling back to RSS summary", url, exc)
        return None


def _parse_rss_entries(raw_content: str) -> list[dict]:
    parsed = feedparser.parse(raw_content)
    entries = []
    for entry in parsed.entries:
        published_at = None
        if entry.get("published_parsed"):
            published_at = datetime(*entry["published_parsed"][:6])
        entries.append({
            "url": entry.get("link"),
            "headline": entry.get("title", ""),
            "summary": entry.get("summary", "") or entry.get("description", ""),
            "published_at": published_at,
        })
    return entries


def _strip_html(text: str) -> str:
    # WordPress's REST API returns title/excerpt as HTML-entity-encoded
    # rendered HTML (e.g. "&#8217;" for a right single quote) -- unescape
    # first so admins see "Broomfield High's ..." instead of "&#8217;s ...",
    # then strip any remaining tags (excerpts are usually a wrapped <p>).
    return re.sub(r"<[^>]+>", " ", html.unescape(text or "")).strip()


def _parse_wp_json_entries(raw_content: str) -> list[dict]:
    """Normalizes a WordPress REST API `/wp-json/wp/v2/posts` response --
    used for sources whose RSS feed is blocked but whose REST API isn't
    (Daily Camera; see app/config.py's NEWS_SOURCES and
    docs/DATA_SOURCE_FINDINGS.md section 6)."""
    posts = json.loads(raw_content)
    entries = []
    for post in posts:
        published_at = None
        raw_date = post.get("date")
        if raw_date:
            try:
                published_at = datetime.fromisoformat(raw_date)
            except ValueError:
                published_at = None
        entries.append({
            "url": post.get("link"),
            "headline": _strip_html(post.get("title", {}).get("rendered", "")),
            "summary": _strip_html(post.get("excerpt", {}).get("rendered", "")),
            "published_at": published_at,
        })
    return entries


def match_article_to_hearing(db: Session, case_numbers: list[str], party_candidates: list[str]) -> Hearing | None:
    for case_number in case_numbers:
        hearing = (
            db.query(Hearing)
            .filter(Hearing.case_number.ilike(case_number), Hearing.status != HearingStatus.cancelled)
            .first()
        )
        if hearing:
            return hearing

    for candidate in party_candidates:
        hearing = (
            db.query(Hearing)
            .filter(Hearing.party_names.ilike(f"%{candidate}%"), Hearing.status != HearingStatus.cancelled)
            .first()
        )
        if hearing:
            return hearing
    return None


def process_feed(db: Session, source_name: str, raw_content: str, now: datetime,
                  source_type: str = "rss") -> tuple[int, int, int]:
    """Returns (articles_seen, auto_matched, queued_for_review).

    `source_type` is "rss" (feedparser, the common case) or "wp_json" (a
    WordPress REST API posts response -- see _parse_wp_json_entries)."""
    if source_type == "wp_json":
        entries = _parse_wp_json_entries(raw_content)
    else:
        entries = _parse_rss_entries(raw_content)

    seen = matched = queued = 0

    for entry in entries:
        url = entry["url"]
        if not url:
            continue
        exists = db.query(NewsMention).filter(NewsMention.article_url == url).first()
        if exists:
            continue  # already processed on a previous run

        seen += 1
        headline = entry["headline"]
        summary = entry["summary"]
        published_at = entry["published_at"]

        text_for_matching = f"{headline}\n{summary}"
        full_text = fetch_article_text(url)
        if full_text:
            text_for_matching += "\n" + full_text

        case_numbers = find_case_numbers_in_text(text_for_matching)
        party_candidates = extract_party_candidates(f"{headline}\n{summary}")

        hearing = match_article_to_hearing(db, case_numbers, party_candidates)

        mention = NewsMention(
            hearing_id=hearing.id if hearing else None,
            article_url=url,
            source_name=source_name,
            headline=headline,
            published_at=published_at,
            extracted_case_numbers=json.dumps(case_numbers),
            extracted_party_candidates=json.dumps(party_candidates),
            match_status=MatchStatus.auto_matched if hearing else MatchStatus.unmatched_review,
            fetched_at=now,
        )
        db.add(mention)
        if hearing:
            matched += 1
        else:
            queued += 1

    return seen, matched, queued


def run_news_monitor(db: Session, feed_texts: dict[str, str] | None = None) -> JobRun:
    """Pass feed_texts (source_name -> raw RSS/XML) to run against fixtures
    (tests) instead of hitting the live network for every configured
    source -- this override path is always treated as `type="rss"`, which
    covers every existing test; a source needing `wp_json` in a test
    instead calls process_feed() directly (see
    tests/test_news_monitor.py::test_daily_camera_wp_json_source)."""
    now = datetime.utcnow()
    job_run = JobRun(job_name=JOB_NAME, started_at=now)
    db.add(job_run)
    db.flush()

    total_seen = total_matched = total_queued = 0
    per_source_errors: dict[str, str] = {}

    if feed_texts is not None:
        sources = [{"name": name, "type": "rss", "url": None, "_raw": raw} for name, raw in feed_texts.items()]
    else:
        sources = [s for s in NEWS_SOURCES if s["name"] not in NEWS_SOURCES_DISABLED]

    for source in sources:
        source_name = source["name"]
        try:
            if "_raw" in source:
                raw_content = source["_raw"]
            else:
                resp = httpx.get(source["url"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                raw_content = resp.text

            seen, matched, queued = process_feed(db, source_name, raw_content, now, source_type=source["type"])
            total_seen += seen
            total_matched += matched
            total_queued += queued
            logger.info("news_monitor[%s]: %d new articles, %d matched, %d queued for review",
                        source_name, seen, matched, queued)
        except Exception as exc:  # noqa: BLE001 - one bad source shouldn't kill the whole run
            logger.warning("news_monitor[%s] failed: %s", source_name, exc)
            per_source_errors[source_name] = str(exc)

    job_run.rows_seen = total_seen
    job_run.rows_upserted = total_matched + total_queued
    job_run.finished_at = datetime.utcnow()

    if per_source_errors and len(per_source_errors) == len(sources):
        # every source failed -- that's a real job failure, not just noise
        job_run.success = False
        job_run.error_message = json.dumps(per_source_errors)
        db.commit()
        alert_job_failure(JOB_NAME, f"All news sources failed: {per_source_errors}")
        return job_run

    job_run.success = True
    if per_source_errors:
        job_run.error_message = "Partial failures: " + json.dumps(per_source_errors)
    db.commit()
    return job_run
