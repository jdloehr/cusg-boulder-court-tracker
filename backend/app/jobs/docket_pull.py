"""
Phase 1 core pipeline (Section 2.1 / 2.4 / 11): pull the Colorado Judicial
Branch docket export CSV for a rolling window, decode + classify + filter
each row, and upsert into the Hearing table with change/cancellation
detection.

Run manually via scripts/run_docket_pull.py, or on a schedule via
jobs/scheduler.py (daily, per Section 8's "data freshness: daily re-pull
minimum").
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.alerting import alert_job_failure
from app.case_categories import decode_case_category
from app.config import COURT_LOCATION_CODES, DOCKET_EXPORT_URL, DOCKET_PULL_WINDOW_DAYS
from app.hearing_types import classify_hearing_type
from app.models import (
    AppearanceType,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    JobRun,
)

logger = logging.getLogger(__name__)

JOB_NAME = "docket_pull"

# Expected columns per Section 2.1. Exposed as a constant so tests and the
# CSV parser agree on what "the export changed shape" means.
EXPECTED_COLUMNS = [
    "Date", "Time", "Duration", "Name", "Case Number",
    "Hearing Type", "Location", "Appearance Type", "Courtroom",
]

# Maps substrings that can appear in the CSV's free-text `Location` column
# to our CourtLocation enum. This is a best-effort mapping (see Section 10
# open question #1) -- unmatched locations fall back to `unknown` and are
# logged, never silently dropped.
LOCATION_TEXT_MAP: list[tuple[str, CourtLocation]] = [
    ("longmont", CourtLocation.longmont_combined),
    ("boulder county court", CourtLocation.boulder_county),
    ("boulder combined", CourtLocation.boulder_district),
    ("boulder district", CourtLocation.boulder_district),
    ("boulder", CourtLocation.boulder_county),  # fallback if just "Boulder"
]


def map_location_text(raw_location: str) -> CourtLocation:
    text = (raw_location or "").strip().lower()
    for needle, loc in LOCATION_TEXT_MAP:
        if needle in text:
            return loc
    return CourtLocation.unknown


def map_appearance_type(raw: str) -> AppearanceType:
    """Section 10 open question #2: what does a *blank* Appearance Type
    mean? Could not be confirmed empirically from this build environment
    (coloradojudicial.gov is unreachable from this sandbox's network -- see
    docs/DATA_SOURCE_FINDINGS.md). We deliberately do NOT assume blank means
    in-person: defaulting an unverified value to "in_person" risks sending a
    student to what's actually a remote-only hearing, which is the one
    outcome this tool exists to prevent. Blank/unrecognized -> `unknown`,
    and `unknown` is excluded from the default in-person filter until a
    human confirms the semantics (see verify_appearance_type_semantics in
    scripts/verify_data_sources.py) and this function is updated."""
    text = (raw or "").strip().upper()
    if text == "IN PERSON":
        return AppearanceType.in_person
    if text in ("REMOTE", "WEBEX", "VIRTUAL", "PHONE", "TELEPHONIC"):
        return AppearanceType.remote
    return AppearanceType.unknown


def build_export_url(start: date, end: date) -> str:
    params = []
    codes = COURT_LOCATION_CODES
    for i, code in enumerate(codes):
        params.append(f"courtLocations[{i}]={code}")
    params.append(f"datesEventScheduled[0]={start.strftime('%Y%m%d')}")
    params.append(f"datesEventScheduled[1]={end.strftime('%Y%m%d')}")
    params.append("language=en")
    return f"{DOCKET_EXPORT_URL}?{'&'.join(params)}"


@dataclass
class ParsedRow:
    case_number: str
    case_category: CaseCategory
    case_category_recognized: bool
    party_names: list[str]
    hearing_type_raw: str
    hearing_type_display: str
    hearing_type_category: str
    date: date
    time: str | None
    duration: str | None
    court_location: CourtLocation
    courtroom: str | None
    appearance_type: AppearanceType


def parse_docket_csv(csv_text: str) -> list[ParsedRow]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ValueError("Docket export returned no CSV header -- empty or malformed response")

    missing = [c for c in EXPECTED_COLUMNS if c not in reader.fieldnames]
    if missing:
        # Section 8: don't silently reshape around a schema change. Fail
        # loudly so an Editor gets alerted rather than the pipeline quietly
        # producing wrong data.
        raise ValueError(
            f"Docket export CSV is missing expected column(s) {missing}. "
            f"Got columns: {reader.fieldnames}. The export's shape may have "
            f"changed -- update EXPECTED_COLUMNS and the parsing below after "
            f"confirming the new format on coloradojudicial.gov/dockets."
        )

    rows: list[ParsedRow] = []
    for raw in reader:
        case_number = (raw.get("Case Number") or "").strip()
        cat_result = decode_case_category(case_number)

        hearing_type_raw = (raw.get("Hearing Type") or "").strip()
        type_result = classify_hearing_type(hearing_type_raw)

        raw_date = (raw.get("Date") or "").strip()
        parsed_date = _parse_date(raw_date)
        if parsed_date is None:
            logger.warning("Skipping row with unparseable date %r (case %s)", raw_date, case_number)
            continue

        party_field = (raw.get("Name") or "").strip()
        party_names = [p.strip() for p in re_split_parties(party_field) if p.strip()]

        rows.append(ParsedRow(
            case_number=case_number,
            case_category=cat_result.category,
            case_category_recognized=cat_result.recognized,
            party_names=party_names,
            hearing_type_raw=hearing_type_raw,
            hearing_type_display=type_result.display,
            hearing_type_category=type_result.category.value,
            date=parsed_date,
            time=(raw.get("Time") or "").strip() or None,
            duration=(raw.get("Duration") or "").strip() or None,
            court_location=map_location_text(raw.get("Location") or ""),
            courtroom=(raw.get("Courtroom") or "").strip() or None,
            appearance_type=map_appearance_type(raw.get("Appearance Type") or ""),
        ))
    return rows


def re_split_parties(name_field: str) -> list[str]:
    """The `Name` column format for multi-party cases isn't documented, so
    this splits on common separators seen in Colorado docket exports ("v.",
    "vs.", ";") without over-fitting to one exact format."""
    if not name_field:
        return []
    parts = re.split(r"\s+v\.?s?\.?\s+|;", name_field, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def _parse_date(raw: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def should_include_by_default(row: ParsedRow) -> bool:
    """Section 5.1 default view: jury trial / oral argument-motions,
    in-person, not juvenile. This is the *default filter*, not an exclusion
    -- rows that don't pass this still get stored (so "show all" / other
    filters and news-mention surfacing in Section 2.2 still work), they
    just don't show up in the default 1-2 week list."""
    if row.case_category == CaseCategory.juvenile:
        return False
    if row.appearance_type != AppearanceType.in_person:
        return False
    return row.hearing_type_category in ("jury_trial", "oral_argument_motions")


def match_existing_hearing(db: Session, row: ParsedRow, exclude_ids: set[str]) -> Hearing | None:
    """Heuristic match of an incoming CSV row to a previously-stored Hearing
    so we can detect date/time/courtroom *changes* rather than treating a
    reschedule as an unrelated new+cancelled pair.

    Key: (source, case_number, hearing_type_raw). `exclude_ids` is the set
    of hearing IDs already touched *by this same pull run* -- excluding
    them is what stops the pipeline from collapsing legitimately distinct
    same-day/same-type rows into one another.

    This was a real bug caught against real live data during build, not a
    hypothetical: the Colorado docket export lists each day of a multi-day
    proceeding (and, less obviously, some unrelated hearings that just
    happen to share a case number and hearing-type string) as separate CSV
    rows. Naively matching same-run rows would collapse, e.g., a 3-day jury
    trial down to 1 stored row picking up whichever date happened to be
    processed last. The live export also, separately, sometimes contains
    outright *duplicate* rows for the same occurrence (identical date/time/
    courtroom) -- also observed during build.

    Both are handled by one rule: a same-run candidate (`id` in
    `exclude_ids`) is only still eligible if its date matches this row's
    date exactly (that's the duplicate-row case -- dedupe onto it); a
    same-run candidate with a *different* date is excluded, forcing a new
    row instead of an incorrect overwrite. Candidates from a *prior* run
    remain eligible regardless of date, which is what lets a genuine
    day-over-day reschedule still be detected as `status=changed` rather
    than new+cancelled.

    When more than one still-eligible candidate shares the key (a case can
    legitimately have two separate motions hearings on different dates,
    say), prefer an exact date match; if none match on date either, treat
    the row as new rather than guessing which stored row it corresponds
    to -- see docs/DATA_SOURCE_FINDINGS.md for why this remains a
    heuristic, not a fully solved problem (the export has no persistent
    hearing ID)."""
    all_matches = (
        db.query(Hearing)
        .filter(
            Hearing.source == HearingSource.state_docket_export,
            Hearing.case_number == row.case_number,
            Hearing.hearing_type_raw == row.hearing_type_raw,
            Hearing.status != HearingStatus.cancelled,
        )
        .all()
    )
    candidates = [c for c in all_matches if c.date == row.date or c.id not in exclude_ids]
    if not candidates:
        return None
    for c in candidates:
        if c.date == row.date:
            return c
    if len(candidates) == 1:
        return candidates[0]
    return None


def upsert_row(db: Session, row: ParsedRow, now: datetime, touched_ids: set[str]) -> tuple[Hearing, bool]:
    """Returns (hearing, is_new). `touched_ids` is passed straight to
    match_existing_hearing() as exclude_ids -- see its docstring."""
    existing = match_existing_hearing(db, row, exclude_ids=touched_ids)
    if existing is None:
        hearing = Hearing(
            source=HearingSource.state_docket_export,
            case_number=row.case_number,
            case_category=row.case_category,
            party_names=json.dumps(row.party_names),
            hearing_type_raw=row.hearing_type_raw,
            hearing_type_display=row.hearing_type_display,
            hearing_type_category=row.hearing_type_category,
            date=row.date,
            time=row.time,
            duration=row.duration,
            court_location=row.court_location,
            courtroom=row.courtroom,
            appearance_type=row.appearance_type,
            is_excluded=(row.case_category == CaseCategory.juvenile),
            exclusion_reason=("Juvenile case (Section 4 default exclusion)"
                               if row.case_category == CaseCategory.juvenile else None),
            status=HearingStatus.scheduled,
            first_seen_at=now,
            last_verified_at=now,
        )
        db.add(hearing)
        return hearing, True

    changed_fields = []
    if existing.date != row.date:
        changed_fields.append(f"date {existing.date} -> {row.date}")
        existing.date = row.date
    if (existing.time or "") != (row.time or ""):
        changed_fields.append(f"time {existing.time!r} -> {row.time!r}")
        existing.time = row.time
    if (existing.courtroom or "") != (row.courtroom or ""):
        changed_fields.append(f"courtroom {existing.courtroom!r} -> {row.courtroom!r}")
        existing.courtroom = row.courtroom

    existing.duration = row.duration
    existing.appearance_type = row.appearance_type
    existing.hearing_type_display = row.hearing_type_display
    existing.hearing_type_category = row.hearing_type_category
    existing.last_verified_at = now

    if changed_fields:
        existing.status = HearingStatus.changed
        existing.change_note = f"Changed as of {now.isoformat(timespec='minutes')}Z: " + "; ".join(changed_fields)

    return existing, False


def mark_missing_as_cancelled(db: Session, window_start: date, window_end: date,
                               touched_ids: set[str], now: datetime) -> int:
    """Any previously-scheduled/changed state-docket hearing inside the
    pulled window that this run did NOT see gets marked cancelled.

    Known limitation (documented, not silently swept under the rug): a
    hearing continued to a date *past* window_end will also look "missing"
    from this pull and get marked cancelled here, even though it may simply
    have moved outside the requested range rather than actually being
    cancelled. Pulling a rolling window daily (Section 8) bounds how long
    that mislabel can persist -- the continued hearing reappears as
    "scheduled" (new) once its new date enters the window, but the
    change_note on the erroneously-cancelled row won't self-correct. A
    production deploy should widen the window or track continuances more
    precisely; flagged here rather than hidden."""
    stale = (
        db.query(Hearing)
        .filter(
            Hearing.source == HearingSource.state_docket_export,
            Hearing.status.in_([HearingStatus.scheduled, HearingStatus.changed]),
            Hearing.date >= window_start,
            Hearing.date <= window_end,
        )
        .all()
    )
    count = 0
    for hearing in stale:
        if hearing.id in touched_ids:
            continue
        hearing.status = HearingStatus.cancelled
        hearing.change_note = (
            f"No longer present in docket export pulled {now.isoformat(timespec='minutes')}Z "
            f"-- likely cancelled or continued outside the {window_start}..{window_end} window."
        )
        count += 1
    return count


def run_docket_pull(db: Session, window_days: int = DOCKET_PULL_WINDOW_DAYS,
                     csv_text: str | None = None) -> JobRun:
    """Main entrypoint. Pass csv_text to run against a fixture (tests) instead
    of hitting the live network."""
    now = datetime.utcnow()
    job_run = JobRun(job_name=JOB_NAME, started_at=now)
    db.add(job_run)
    db.flush()

    window_start = now.date()
    window_end = window_start + timedelta(days=window_days)

    try:
        if csv_text is None:
            url = build_export_url(window_start, window_end)
            resp = httpx.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            csv_text = resp.text

        rows = parse_docket_csv(csv_text)
        job_run.rows_seen = len(rows)

        if len(rows) == 0:
            # Section 8: "notify an Editor if a scheduled pull ... returns
            # unexpectedly empty data" -- an empty result for a multi-week
            # Boulder-area window is suspicious, not normal.
            raise ValueError("Docket export returned zero rows for the requested window -- "
                              "treating as a likely failure rather than 'no hearings scheduled'.")

        touched_ids: set[str] = set()
        upserted = 0
        for row in rows:
            hearing, _is_new = upsert_row(db, row, now, touched_ids)
            db.flush()  # assign hearing.id if new
            touched_ids.add(hearing.id)
            upserted += 1

        cancelled = mark_missing_as_cancelled(db, window_start, window_end, touched_ids, now)

        job_run.rows_upserted = upserted
        job_run.success = True
        job_run.finished_at = datetime.utcnow()
        db.commit()
        logger.info("docket_pull: %d rows seen, %d upserted, %d marked cancelled",
                    len(rows), upserted, cancelled)
        return job_run

    except Exception as exc:  # noqa: BLE001 - deliberately broad: this is a job boundary
        db.rollback()
        job_run.success = False
        job_run.error_message = str(exc)
        job_run.finished_at = datetime.utcnow()
        db.add(job_run)
        db.commit()
        alert_job_failure(JOB_NAME, str(exc))
        raise
