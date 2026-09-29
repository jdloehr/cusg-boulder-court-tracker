"""
Phase 8 doc: news tracking system rebuild. Replaces test_news_monitor.py
(deleted) and test_news_matching.py (deleted) -- the old RSS-polling and
fuzzy-classification tests have no equivalent in the new per-hearing-
search, deterministic case-number-found-or-not model.
"""
import json
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.jobs.news_search import (
    build_search_query,
    classify_search_item,
    run_news_search,
    search_for_hearing,
)
from app.models import (
    AppearanceType,
    Base,
    CaseCategory,
    CourtLocation,
    ExternalApiUsage,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    MatchStatus,
    NewsMention,
    SourceType,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_hearing(db, **overrides):
    defaults = dict(
        id=overrides.pop("id", "hearing-1"),
        source=HearingSource.state_docket_export,
        case_number="2026CR001452",
        case_category=CaseCategory.criminal,
        party_names=json.dumps(["JOHN CARLSTROM"]),
        hearing_type_raw="Jury Trial",
        hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value,
        date=date.today() + timedelta(days=10),
        court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    defaults.update(overrides)
    hearing = Hearing(**defaults)
    db.add(hearing)
    db.commit()
    return hearing


# --- Pure-function tests -----------------------------------------------------


def test_build_search_query_uses_the_first_usable_party_name():
    hearing = Hearing(party_names=json.dumps(["JOHN CARLSTROM"]), case_number="x")
    assert build_search_query(hearing) == "JOHN CARLSTROM Boulder court"


def test_build_search_query_skips_generic_captions():
    hearing = Hearing(party_names=json.dumps(["STATE OF COLORADO", "JOHN CARLSTROM"]), case_number="x")
    assert build_search_query(hearing) == "JOHN CARLSTROM Boulder court"


def test_build_search_query_returns_none_when_no_usable_name():
    hearing = Hearing(party_names=json.dumps(["STATE OF COLORADO"]), case_number="x")
    assert build_search_query(hearing) is None


def test_build_search_query_returns_none_when_party_names_missing():
    hearing = Hearing(party_names=None, case_number="x")
    assert build_search_query(hearing) is None


def test_classify_search_item_finds_the_hearings_own_case_number():
    hearing = Hearing(case_number="2026CR001452")
    item = {"title": "Man charged in case 2026CR001452", "snippet": "...", "link": "https://dailycamera.com/x"}
    status, source_type = classify_search_item(item, hearing)
    assert status == MatchStatus.auto_matched
    assert source_type == SourceType.search_result_case_number


def test_classify_search_item_detects_a_da_press_release_by_url():
    hearing = Hearing(case_number="2026CR001452")
    item = {"title": "Charges filed, case 2026CR001452", "snippet": "", "link": "https://bouldercounty.gov/press/x"}
    status, source_type = classify_search_item(item, hearing)
    assert status == MatchStatus.auto_matched
    assert source_type == SourceType.da_press_release


def test_classify_search_item_falls_back_to_tier_2_with_no_case_number():
    hearing = Hearing(case_number="2026CR001452")
    item = {"title": "Local man in court", "snippet": "no case number here", "link": "https://dailycamera.com/x"}
    status, source_type = classify_search_item(item, hearing)
    assert status == MatchStatus.in_weekly_reading_list
    assert source_type == SourceType.search_result_general


def test_classify_search_item_a_different_case_number_is_still_tier_2():
    # A result mentioning some OTHER real case number shouldn't be
    # mistaken for a match on this hearing's own case.
    hearing = Hearing(case_number="2026CR001452")
    item = {"title": "Unrelated case 2026CR009999 update", "snippet": "", "link": "https://dailycamera.com/x"}
    status, _ = classify_search_item(item, hearing)
    assert status == MatchStatus.in_weekly_reading_list


# --- Job-level tests, mocked search API --------------------------------------


def _mock_search(monkeypatch, items):
    def fake_get(url, params=None, timeout=None):
        return httpx.Response(200, json={"items": items}, request=httpx.Request("GET", url))
    monkeypatch.setattr("app.jobs.news_search.httpx.get", fake_get)


def test_search_for_hearing_creates_a_tier1_mention(db, monkeypatch):
    hearing = _make_hearing(db)
    _mock_search(monkeypatch, [
        {"title": "Trial begins for case 2026CR001452", "snippet": "", "link": "https://dailycamera.com/a"},
    ])
    outcome = search_for_hearing(db, hearing, datetime.utcnow())
    assert outcome.status == "tier1"
    mention = db.query(NewsMention).filter_by(hearing_id=hearing.id).one()
    assert mention.match_status == MatchStatus.auto_matched


def test_search_for_hearing_creates_a_tier2_mention_when_no_case_number(db, monkeypatch):
    hearing = _make_hearing(db)
    _mock_search(monkeypatch, [
        {"title": "Carlstrom case update", "snippet": "no case number mentioned", "link": "https://dailycamera.com/a"},
    ])
    outcome = search_for_hearing(db, hearing, datetime.utcnow())
    assert outcome.status == "tier2"
    mention = db.query(NewsMention).filter_by(hearing_id=hearing.id).one()
    assert mention.match_status == MatchStatus.in_weekly_reading_list


def test_search_for_hearing_returns_no_results_when_google_finds_nothing(db, monkeypatch):
    hearing = _make_hearing(db)
    _mock_search(monkeypatch, [])
    outcome = search_for_hearing(db, hearing, datetime.utcnow())
    assert outcome.status == "no_results"
    assert db.query(NewsMention).filter_by(hearing_id=hearing.id).first() is None


def test_search_for_hearing_skips_an_already_resolved_hearing_without_calling_the_api(db, monkeypatch):
    hearing = _make_hearing(db)
    db.add(NewsMention(hearing_id=hearing.id, article_url="https://x", source_name="x",
                        headline="x", match_status=MatchStatus.manually_linked))
    db.commit()

    called = {"n": 0}
    def fake_get(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call the search API for an already-resolved hearing")
    monkeypatch.setattr("app.jobs.news_search.httpx.get", fake_get)

    outcome = search_for_hearing(db, hearing, datetime.utcnow())
    assert outcome.status == "skipped_resolved"
    assert called["n"] == 0


def test_search_for_hearing_updates_an_existing_reading_list_row_in_place(db, monkeypatch):
    hearing = _make_hearing(db)
    existing = NewsMention(hearing_id=hearing.id, article_url="https://old", source_name="old",
                            headline="old headline", match_status=MatchStatus.in_weekly_reading_list)
    db.add(existing)
    db.commit()

    _mock_search(monkeypatch, [
        {"title": "Trial begins for case 2026CR001452", "snippet": "", "link": "https://dailycamera.com/new"},
    ])
    search_for_hearing(db, hearing, datetime.utcnow())

    rows = db.query(NewsMention).filter_by(hearing_id=hearing.id).all()
    assert len(rows) == 1  # updated in place, not a second row
    assert rows[0].match_status == MatchStatus.auto_matched
    assert rows[0].article_url == "https://dailycamera.com/new"


def test_search_for_hearing_with_no_usable_party_name_is_a_clean_skip(db, monkeypatch):
    hearing = _make_hearing(db, party_names=json.dumps(["STATE OF COLORADO"]))
    outcome = search_for_hearing(db, hearing, datetime.utcnow())
    assert outcome.status == "no_query"


def test_search_for_hearing_catches_exceptions_and_never_raises(db, monkeypatch):
    hearing = _make_hearing(db)
    def fake_get(*a, **k):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr("app.jobs.news_search.httpx.get", fake_get)
    monkeypatch.setattr("app.jobs.news_search.time.sleep", lambda *_a: None)  # skip real backoff delays

    outcome = search_for_hearing(db, hearing, datetime.utcnow())
    assert outcome.status == "error"


def test_search_for_hearing_records_usage_per_outbound_attempt(db, monkeypatch):
    hearing = _make_hearing(db)
    _mock_search(monkeypatch, [{"title": "x 2026CR001452", "snippet": "", "link": "https://dailycamera.com/a"}])
    search_for_hearing(db, hearing, datetime.utcnow())
    usage = db.query(ExternalApiUsage).filter_by(api_name="google_custom_search").one()
    assert usage.query_count == 1


# --- run_news_search cadence tests -------------------------------------------


def test_run_news_search_does_an_initial_search_for_a_brand_new_hearing(db, monkeypatch):
    hearing = _make_hearing(db)
    assert hearing.news_search_initial_at is None
    _mock_search(monkeypatch, [{"title": "x 2026CR001452", "snippet": "", "link": "https://dailycamera.com/a"}])

    job = run_news_search(db, datetime.utcnow())
    db.refresh(hearing)
    assert job.success is True
    assert job.rows_seen == 1
    assert hearing.news_search_initial_at is not None


def test_run_news_search_prehearing_pass_skips_a_hearing_outside_the_window(db, monkeypatch):
    hearing = _make_hearing(db, date=date.today() + timedelta(days=30))
    hearing.news_search_initial_at = datetime.utcnow()  # pretend pass 1 already ran
    db.commit()
    _mock_search(monkeypatch, [])

    job = run_news_search(db, datetime.utcnow())
    db.refresh(hearing)
    assert job.rows_seen == 0  # not eligible for pass 1 (already done) or pass 2 (too far out)
    assert hearing.news_search_prehearing_at is None


def test_run_news_search_prehearing_pass_runs_for_an_unresolved_hearing_near_its_date(db, monkeypatch):
    hearing = _make_hearing(db, date=date.today() + timedelta(days=2))
    hearing.news_search_initial_at = datetime.utcnow()
    db.commit()
    _mock_search(monkeypatch, [{"title": "x 2026CR001452", "snippet": "", "link": "https://dailycamera.com/a"}])

    job = run_news_search(db, datetime.utcnow())
    db.refresh(hearing)
    assert job.rows_seen == 1
    assert hearing.news_search_prehearing_at is not None


def test_run_news_search_prehearing_pass_skips_a_hearing_already_resolved(db, monkeypatch):
    hearing = _make_hearing(db, date=date.today() + timedelta(days=2))
    hearing.news_search_initial_at = datetime.utcnow()
    db.add(NewsMention(hearing_id=hearing.id, article_url="https://x", source_name="x",
                        headline="x", match_status=MatchStatus.dismissed))
    db.commit()

    called = {"n": 0}
    def fake_get(*a, **k):
        called["n"] += 1
        raise AssertionError("should not search a hearing with a resolved status")
    monkeypatch.setattr("app.jobs.news_search.httpx.get", fake_get)

    job = run_news_search(db, datetime.utcnow())
    assert job.rows_seen == 0
    assert called["n"] == 0


def test_run_news_search_does_not_stamp_the_timestamp_on_a_genuine_error(db, monkeypatch):
    hearing = _make_hearing(db)
    def fake_get(*a, **k):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr("app.jobs.news_search.httpx.get", fake_get)
    monkeypatch.setattr("app.jobs.news_search.time.sleep", lambda *_a: None)

    run_news_search(db, datetime.utcnow())
    db.refresh(hearing)
    assert hearing.news_search_initial_at is None  # retried next run, not permanently skipped


def test_run_news_search_alerts_when_every_hearing_fails(db, monkeypatch):
    _make_hearing(db)
    alerts = []
    monkeypatch.setattr("app.jobs.news_search.alert_job_failure", lambda *a, **k: alerts.append((a, k)))
    def fake_get(*a, **k):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr("app.jobs.news_search.httpx.get", fake_get)
    monkeypatch.setattr("app.jobs.news_search.time.sleep", lambda *_a: None)

    run_news_search(db, datetime.utcnow())
    assert len(alerts) == 1
    assert alerts[0][1].get("severity") == "low"


def test_run_news_search_ignores_hearings_outside_the_eligible_types(db, monkeypatch):
    _make_hearing(db, hearing_type_category=HearingTypeCategory.other.value)
    job = run_news_search(db, datetime.utcnow())
    assert job.rows_seen == 0


def test_run_news_search_ignores_cancelled_hearings(db, monkeypatch):
    _make_hearing(db, status=HearingStatus.cancelled)
    job = run_news_search(db, datetime.utcnow())
    assert job.rows_seen == 0
