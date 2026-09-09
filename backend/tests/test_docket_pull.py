"""
Tests the full docket-pull pipeline (parse -> decode -> classify -> filter
-> upsert/diff) against tests/fixtures/sample_docket_export.csv.

That fixture is a SYNTHETIC file I wrote by hand, matching the exact column
format documented in Section 2.1. It is NOT real docket data; case numbers,
names, and dates are made up. It exists to exercise every branch of the
pipeline deterministically (jury trial, oral argument/motions, juvenile
exclusion, blank appearance type, an unrecognized case-number prefix, an
unrecognized hearing-type string, an exact-duplicate row, and a same-case
same-type-different-date pair) -- including a few edge cases that were
only *discovered* by later running this same pipeline against the real
live export (see docs/DATA_SOURCE_FINDINGS.md) and are reproduced here in
miniature so they stay covered by a fast, deterministic test.
"""
from datetime import date
from pathlib import Path

from app.jobs.docket_pull import (
    build_export_url,
    map_appearance_type,
    map_location_text,
    parse_docket_csv,
    run_docket_pull,
    should_include_by_default,
)
from app.models import (
    AppearanceType,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingStatus,
    HearingTypeCategory,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_docket_export.csv").read_text()


def test_build_export_url_uses_configured_court_codes_and_date_range():
    url = build_export_url(date(2026, 9, 9), date(2026, 10, 7))
    assert "datesEventScheduled[0]=20260909" in url
    assert "datesEventScheduled[1]=20261007" in url
    assert "courtLocations[0]=" in url
    assert "language=en" in url


def test_parse_docket_csv_decodes_every_row():
    rows = parse_docket_csv(FIXTURE)
    assert len(rows) == 11

    by_case = {r.case_number: r for r in rows}

    dawson = by_case["2026CR001452"]
    assert dawson.case_category == CaseCategory.criminal
    assert dawson.hearing_type_category == HearingTypeCategory.jury_trial.value
    assert dawson.appearance_type == AppearanceType.in_person
    assert dawson.court_location == CourtLocation.boulder_county

    juvenile = by_case["2026JV000045"]
    assert juvenile.case_category == CaseCategory.juvenile

    unrecognized_prefix = by_case["2026XY000777"]
    assert unrecognized_prefix.case_category == CaseCategory.other
    assert unrecognized_prefix.case_category_recognized is False

    whitfield = by_case["2026CR001100"]
    assert whitfield.appearance_type == AppearanceType.unknown  # blank in CSV

    civil = by_case["2026CV000980"]
    assert civil.court_location == CourtLocation.boulder_district


def test_parse_docket_csv_rejects_missing_columns():
    import pytest
    bad_csv = "Date,Time,Name\n09/22/2026,9:00 AM,Someone\n"
    with pytest.raises(ValueError, match="missing expected column"):
        parse_docket_csv(bad_csv)


def test_map_appearance_type_blank_is_unknown_not_assumed_in_person():
    # Section 10 open question #2 -- deliberately conservative, see the
    # docstring on map_appearance_type().
    assert map_appearance_type("") == AppearanceType.unknown
    assert map_appearance_type("IN PERSON") == AppearanceType.in_person
    assert map_appearance_type("REMOTE") == AppearanceType.remote


def test_map_location_text_boulder_variants():
    assert map_location_text("Boulder County Justice Center") == CourtLocation.boulder_county
    assert map_location_text("Boulder Combined Court") == CourtLocation.boulder_district
    assert map_location_text("Longmont Municipal Building") == CourtLocation.longmont_combined
    assert map_location_text("Some Other Building") == CourtLocation.unknown


def test_default_filter_matches_section_5_1():
    rows = parse_docket_csv(FIXTURE)
    included = {r.case_number for r in rows if should_include_by_default(r)}
    # Jury trial, in person -> included
    assert "2026CR001452" in included
    # Motions hearing, in person -> included
    assert "2026M004410" in included
    # Oral argument, in person -> included
    assert "2026T005522" in included
    # Suppression Hearing classifies as oral_argument_motions -> included
    assert "2026CR002001" in included

    # Jury trial but blank/unknown appearance type -> excluded from default
    assert "2026CR001100" not in included
    # Juvenile -> excluded from default regardless of hearing type
    assert "2026JV000045" not in included
    # Permanent Orders Hearing / Return Date / Advisement -> not our two focus types
    assert "2026DR000221" not in included
    assert "2026M009981" not in included
    assert "2026PR000089" not in included


def test_run_docket_pull_inserts_all_rows_and_excludes_juvenile(db):
    job = run_docket_pull(db, window_days=45, csv_text=FIXTURE)
    assert job.success is True
    assert job.rows_seen == 11
    assert job.rows_upserted == 11

    all_hearings = db.query(Hearing).all()
    assert len(all_hearings) == 11

    juvenile = db.query(Hearing).filter(Hearing.case_number == "2026JV000045").first()
    assert juvenile.is_excluded is True
    assert "Juvenile" in juvenile.exclusion_reason


def test_run_docket_pull_dedupes_exact_duplicate_rows_in_one_pull(db):
    """Real live pulls during build contained exact duplicate CSV rows
    (identical case number, hearing type, date, time, and courtroom) --
    this should collapse to one stored Hearing, not two."""
    duplicated_csv = FIXTURE + (
        "09/22/2026,9:00 AM,2 hours,People v. Dawson,2026CR001452,Jury Trial,"
        "Boulder County Justice Center,IN PERSON,C\n"
    )
    job = run_docket_pull(db, window_days=45, csv_text=duplicated_csv)
    assert job.rows_seen == 12  # the duplicate line is still parsed...
    matches = db.query(Hearing).filter(Hearing.case_number == "2026CR001452").all()
    assert len(matches) == 1  # ...but collapses onto the same stored row
    assert matches[0].status == HearingStatus.scheduled  # not marked "changed" -- nothing differs


def test_run_docket_pull_keeps_distinct_same_day_type_occurrences_separate(db):
    """A case can have two separate hearings of the SAME type on DIFFERENT
    dates in one pull (e.g. a multi-day trial) -- these must NOT collapse
    into each other the way the exact-duplicate case above does."""
    two_day_trial_csv = FIXTURE + (
        "09/23/2026,9:00 AM,2 hours,People v. Dawson,2026CR001452,Jury Trial,"
        "Boulder County Justice Center,IN PERSON,C\n"
    )
    job = run_docket_pull(db, window_days=45, csv_text=two_day_trial_csv)
    assert job.rows_seen == 12
    matches = db.query(Hearing).filter(Hearing.case_number == "2026CR001452").all()
    assert len(matches) == 2
    assert {m.date for m in matches} == {date(2026, 9, 22), date(2026, 9, 23)}
    assert all(m.status == HearingStatus.scheduled for m in matches)


def test_run_docket_pull_is_idempotent_on_unchanged_rerun(db):
    run_docket_pull(db, window_days=45, csv_text=FIXTURE)
    first_ids = {h.id for h in db.query(Hearing).all()}

    run_docket_pull(db, window_days=45, csv_text=FIXTURE)
    second_ids = {h.id for h in db.query(Hearing).all()}

    assert first_ids == second_ids  # no duplicate rows created
    for h in db.query(Hearing).all():
        assert h.status == HearingStatus.scheduled  # nothing changed, so status untouched


def test_run_docket_pull_detects_reschedule_as_changed(db):
    run_docket_pull(db, window_days=45, csv_text=FIXTURE)

    moved_csv = FIXTURE.replace(
        "09/22/2026,9:00 AM,2 hours,People v. Dawson,2026CR001452,Jury Trial,Boulder County Justice Center,IN PERSON,C",
        "09/24/2026,1:00 PM,2 hours,People v. Dawson,2026CR001452,Jury Trial,Boulder County Justice Center,IN PERSON,G",
    )
    run_docket_pull(db, window_days=45, csv_text=moved_csv)

    dawson = db.query(Hearing).filter(Hearing.case_number == "2026CR001452").one()
    assert dawson.status == HearingStatus.changed
    assert "date" in dawson.change_note
    assert "courtroom" in dawson.change_note
    assert dawson.date == date(2026, 9, 24)
    assert dawson.courtroom == "G"


def test_run_docket_pull_marks_disappeared_hearing_cancelled(db):
    run_docket_pull(db, window_days=45, csv_text=FIXTURE)

    lines = FIXTURE.splitlines()
    without_dawson = "\n".join(l for l in lines if "2026CR001452" not in l) + "\n"
    run_docket_pull(db, window_days=45, csv_text=without_dawson)

    dawson = db.query(Hearing).filter(Hearing.case_number == "2026CR001452").one()
    assert dawson.status == HearingStatus.cancelled
    assert "cancelled" in dawson.change_note.lower()


def test_run_docket_pull_raises_and_records_failure_on_empty_result(db):
    import pytest
    with pytest.raises(ValueError, match="zero rows"):
        run_docket_pull(db, window_days=45, csv_text="Date,Time,Duration,Name,Case Number,Hearing Type,"
                                                       "Location,Appearance Type,Courtroom\n")

    from app.models import JobRun
    job = db.query(JobRun).order_by(JobRun.started_at.desc()).first()
    assert job.success is False
    assert "zero rows" in job.error_message
