"""
app/jobs/news_matching.py -- the confidence-tiered matching logic itself,
independent of feed-fetching/parsing (see test_news_monitor.py for the
end-to-end pipeline tests). Built against real evidence -- see that
module's own docstring -- so these tests prove the specific improvements
that evidence justified (fuzzy first-name/middle-initial tolerance, date-
proximity gating, the relevance-based discard gate), not the Phase-6
doc's original (and, on the evidence, incorrect) "LASTNAME, FIRSTNAME"
assumption.
"""
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.jobs.news_matching import (
    MatchEvaluation,
    date_proximity_days,
    evaluate_match,
    has_court_relevance,
    name_match_score,
)
from app.models import (
    AppearanceType,
    Base,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    MatchConfidence,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _hearing(case_number, party_names, hearing_date, category=CaseCategory.criminal):
    return Hearing(
        source=HearingSource.state_docket_export, case_number=case_number, case_category=category,
        party_names=json.dumps(party_names), hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=hearing_date,
        court_location=CourtLocation.boulder_county, appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )


# --- name_match_score ---------------------------------------------------------

def test_exact_name_match_scores_1():
    assert name_match_score("John Carlstrom", "JOHN CARLSTROM") == 1.0


def test_different_last_name_scores_zero():
    assert name_match_score("John Smith", "JOHN CARLSTROM") == 0.0


def test_middle_initial_does_not_sink_an_otherwise_strong_match():
    # Real gap the Phase-6 doc called out: "middle initials, nicknames"
    # shouldn't zero out a match.
    score = name_match_score("John Carlstrom", "JOHN A CARLSTROM")
    assert score == 1.0  # normalize_name_tokens compares first/last only


def test_initial_vs_full_first_name_scores_high_but_not_perfect():
    score = name_match_score("J. Carlstrom", "JOHN CARLSTROM")
    assert 0.85 <= score < 1.0


def test_minor_spelling_difference_scores_partial_credit():
    score = name_match_score("Jon Carlstrom", "JOHN CARLSTROM")
    assert 0.5 < score < 1.0


def test_single_word_names_never_match():
    assert name_match_score("Carlstrom", "JOHN CARLSTROM") == 0.0
    assert name_match_score("John Carlstrom", "PEOPLE") == 0.0


# --- date_proximity_days --------------------------------------------------------

def test_date_proximity_none_when_either_side_missing():
    assert date_proximity_days(None, date(2026, 9, 1)) is None


def test_date_proximity_computes_absolute_day_difference():
    published = datetime(2026, 9, 1)
    assert date_proximity_days(published, date(2026, 9, 15)) == 14
    assert date_proximity_days(published, date(2026, 8, 25)) == 7


# --- has_court_relevance ---------------------------------------------------------

def test_court_relevance_detects_obvious_keywords():
    assert has_court_relevance("Man sentenced to prison after guilty plea") is True


def test_court_relevance_false_for_generic_local_news():
    assert has_court_relevance("Boulder Valley school board votes to close four elementary schools") is False


# --- evaluate_match: case number path -------------------------------------------

def test_case_number_match_is_always_high_confidence_regardless_of_date(db):
    # Case number is unambiguous -- no date-window gating, unlike name matching.
    hearing = _hearing("2026CR001452", ["Alex Dawson"], date(2026, 9, 22))
    db.add(hearing)
    db.commit()

    far_away_publish = datetime(2026, 1, 1)  # ~9 months off
    result = evaluate_match(db, ["2026CR001452"], [], far_away_publish, "some article text")
    assert result.confidence == MatchConfidence.high
    assert result.hearing.id == hearing.id
    assert result.signals["case_number_matched"] == "2026CR001452"


# --- evaluate_match: name-based path --------------------------------------------

def test_strong_name_match_within_date_window_is_high_confidence(db):
    hearing = _hearing("2026CR001452", ["Alex Dawson"], date(2026, 9, 22))
    db.add(hearing)
    db.commit()

    published = datetime(2026, 9, 10)  # 12 days before -- within the 21-day window
    result = evaluate_match(db, [], ["Alex Dawson"], published, "Alex Dawson case draws attention")
    assert result.confidence == MatchConfidence.high
    assert result.hearing.id == hearing.id


def test_strong_name_match_with_no_known_publish_date_is_only_medium_confidence(db):
    # High confidence requires date-proximity *agreement* (Section 3), not
    # just a strong name score -- an article whose publish date couldn't
    # be parsed at all can't demonstrate that agreement, even with an
    # otherwise-perfect name match. The hearing is still found (no date
    # to filter the SQL-level candidate search by), just not confidently
    # enough to auto-attach.
    hearing = _hearing("2026CR001452", ["Alex Dawson"], date(2026, 9, 22))
    db.add(hearing)
    db.commit()

    result = evaluate_match(db, [], ["Alex Dawson"], None, "Alex Dawson case draws attention")
    assert result.confidence == MatchConfidence.medium
    assert result.hearing.id == hearing.id
    assert result.signals["date_proximity_days"] is None


def test_fuzzy_first_name_match_is_medium_not_high(db):
    hearing = _hearing("2026CR001452", ["Jonathan Dawson"], date(2026, 9, 22))
    db.add(hearing)
    db.commit()

    published = datetime(2026, 9, 10)
    result = evaluate_match(db, [], ["Jon Dawson"], published, "Jon Dawson case draws attention")
    assert result.confidence == MatchConfidence.medium
    assert result.hearing.id == hearing.id


def test_category_mismatch_demotes_an_otherwise_strong_match(db):
    # Article reads as criminal (arrest/charged language); the matched
    # hearing is domestic_relations -- Section 2's "signal to lower
    # confidence rather than auto-match."
    hearing = _hearing("2026DR000221", ["Alex Dawson"], date(2026, 9, 22),
                        category=CaseCategory.domestic_relations)
    db.add(hearing)
    db.commit()

    published = datetime(2026, 9, 10)
    result = evaluate_match(
        db, [], ["Alex Dawson"], published,
        "Alex Dawson was arrested and charged after an incident downtown",
    )
    assert result.confidence == MatchConfidence.medium
    assert result.signals["category_consistent"] is False


def test_hearing_outside_date_window_is_not_even_considered(db):
    hearing = _hearing("2026CR001452", ["Alex Dawson"], date(2026, 9, 22))
    db.add(hearing)
    db.commit()

    published = datetime(2026, 1, 1)  # far outside the +/-21 day window
    result = evaluate_match(db, [], ["Alex Dawson"], published, "Alex Dawson case draws attention")
    assert result.hearing is None
    assert result.confidence == MatchConfidence.low


# --- evaluate_match: no match at all -> discard gate ----------------------------

def test_no_signal_at_all_should_discard(db):
    result = evaluate_match(db, [], [], datetime(2026, 9, 10), "Boulder Valley school board votes to close schools")
    assert result.hearing is None
    assert result.should_discard is True


def test_no_case_number_no_name_match_but_court_relevant_language_is_not_discarded(db):
    # The real headline that drove this gate's design: "Former deputy
    # accused of punching wife in Longmont gets probation as part of
    # plea" -- no extractable name in the headline, but clearly worth a
    # human's attention.
    result = evaluate_match(
        db, [], [], datetime(2026, 9, 10),
        "Former deputy accused of punching wife in Longmont gets probation as part of plea",
    )
    assert result.hearing is None
    assert result.should_discard is False


def test_case_number_found_is_never_discarded_even_with_no_hearing_match(db):
    # A case number was found in the text, but no hearing with that
    # number exists (yet) -- still worth a human's attention, not noise.
    result = evaluate_match(db, ["2026CR999999"], [], datetime(2026, 9, 10), "some minor article text")
    assert result.hearing is None
    assert result.should_discard is False


def test_should_discard_is_false_whenever_a_hearing_is_attached(db):
    hearing = _hearing("2026CR001452", ["Alex Dawson"], date(2026, 9, 22))
    db.add(hearing)
    db.commit()
    result = MatchEvaluation(hearing=hearing, confidence=MatchConfidence.medium, signals={})
    assert result.should_discard is False
