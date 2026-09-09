"""
News-monitoring pipeline tests.

Two kinds of fixture are used here, and they are NOT interchangeable --
see docs/DATA_SOURCE_FINDINGS.md for the full story:

1. REAL fetched data (tests/fixtures/real_*.xml and real_*.json),
   downloaded live from Boulder Reporting Lab, Daily Camera (via its
   WordPress REST API -- see below), CU Independent, Colorado Sun, and
   9News during this build (dated 2026-09-08/09). These prove the
   extraction pipeline runs against genuine news content and correctly
   reaches Section 2.2's documented "no clean case number in the article
   -> queue for manual review" outcome, because that's what these
   particular real articles actually do -- including confirming, via a
   real article's own text, that a high-profile Boulder-arrest story
   (Barry Morphew) is actually being prosecuted in Alamosa County, not
   Boulder, which is exactly the kind of judgment call the review queue
   exists for.

2. Hand-written SYNTHETIC feed XML (inline in this file, clearly marked),
   used only to prove the *positive* match path (case-number match and
   party-name-fallback match) end-to-end, since none of the real articles
   fetched during build happened to name a Boulder case number or a party
   already in the live-pulled Hearing table. Do not mistake these for real
   news content -- the case numbers, names, and URLs are made up.
"""
import json
from pathlib import Path

from app.jobs.news_monitor import extract_party_candidates, process_feed, run_news_monitor
from app.models import CaseCategory, CourtLocation, Hearing, HearingSource, HearingStatus, HearingTypeCategory, \
    AppearanceType, JobRun, MatchStatus, NewsMention

FIXTURES = Path(__file__).parent / "fixtures"


def _make_hearing(case_number: str, party_names: list[str]) -> Hearing:
    return Hearing(
        source=HearingSource.state_docket_export,
        case_number=case_number,
        case_category=CaseCategory.criminal,
        party_names=json.dumps(party_names),
        hearing_type_raw="Jury Trial",
        hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value,
        date=__import__("datetime").date(2026, 9, 22),
        court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )


def test_extract_party_candidates_from_real_headline():
    # Real headline fetched from the Colorado Sun RSS feed during build.
    headline = "Former CBI scientist Missy Woods sentenced to prison in DNA scandal"
    candidates = extract_party_candidates(headline)
    assert any("Woods" in c for c in candidates)


def test_extract_party_candidates_does_not_cross_line_breaks():
    # Real bug, caught running live against a real Daily Camera article
    # (see app/jobs/news_monitor.py's comment on _NAME_RUN_RE): the last
    # capitalized word of a headline was gluing onto the first capitalized
    # word of the next line via `\s+` matching a newline.
    text = "Single-engine plane crashes in Colorado mountains near Telluride\nColorado search and rescue crews are responding."
    candidates = extract_party_candidates(text)
    assert not any("\n" in c for c in candidates)
    assert "Telluride\nColorado" not in candidates


def test_extract_party_candidates_filters_place_and_institution_names():
    # Also real, from the same article: none of these are people.
    text = ("Colorado search and rescue crews are responding to a single-engine "
            "plane crash on Dolores Peak near Telluride, the San Miguel County "
            "Sheriff's Office said Thursday.")
    candidates = extract_party_candidates(text)
    assert candidates == []


def test_real_colorado_sun_feed_court_article_has_no_clean_case_number_and_queues_for_review(db, monkeypatch):
    # Confirmed live during build: fetching the full article body for this
    # piece also does not surface a case number (Colorado courts don't
    # print case numbers in press coverage as a rule) -- stub the full-text
    # fetch here so the test is deterministic and network-free rather than
    # re-hitting the live site on every run.
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)

    feed_text = (FIXTURES / "real_coloradosun_feed.xml").read_text()
    seen, matched, queued = process_feed(db, "Colorado Sun", feed_text, __import__("datetime").datetime.utcnow())

    assert seen > 0
    mentions = db.query(NewsMention).filter(NewsMention.source_name == "Colorado Sun").all()
    sentencing_mentions = [m for m in mentions if "Woods" in m.headline]
    assert len(sentencing_mentions) == 1
    mention = sentencing_mentions[0]
    assert mention.match_status == MatchStatus.unmatched_review
    assert mention.hearing_id is None
    assert json.loads(mention.extracted_case_numbers) == []


def test_real_9news_feed_court_articles_are_found_and_queued(db, monkeypatch):
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    feed_text = (FIXTURES / "real_9news_feed.xml").read_text()
    seen, matched, queued = process_feed(db, "9News", feed_text, __import__("datetime").datetime.utcnow())
    assert seen > 0
    headlines = [m.headline for m in db.query(NewsMention).filter(NewsMention.source_name == "9News").all()]
    assert any("sentenced" in h.lower() or "morphew" in h.lower() for h in headlines)


def test_real_boulder_reporting_lab_feed_parses_without_error(db, monkeypatch):
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    feed_text = (FIXTURES / "real_boulderreportinglab_feed.xml").read_text()
    seen, matched, queued = process_feed(db, "Boulder Reporting Lab", feed_text, __import__("datetime").datetime.utcnow())
    assert seen == 10  # feed had 10 items as of the 2026-09-08 fetch


def test_real_cu_independent_feed_parses_without_error(db, monkeypatch):
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    feed_text = (FIXTURES / "real_cuindependent_feed.xml").read_text()
    seen, matched, queued = process_feed(db, "CU Independent", feed_text, __import__("datetime").datetime.utcnow())
    assert seen == 10


def test_daily_camera_wp_json_source_real_data(db, monkeypatch):
    """Daily Camera's own RSS feed returns HTTP 403 to automated fetches
    (confirmed during build), but its WordPress REST API doesn't -- see
    NEWS_SOURCES in app/config.py. This fixture is real data fetched live
    from https://www.dailycamera.com/wp-json/wp/v2/posts?categories=41
    ("Crime and Public Safety"), not synthetic.

    One of these real articles (the Barry Morphew bond story) is a strong
    real-world test of the review queue's judgment-call purpose: the
    article's own excerpt says the bond hearing was in Alamosa County, not
    Boulder, so this correctly stays unmatched rather than getting
    force-matched to some unrelated Boulder hearing."""
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    raw_json = (FIXTURES / "real_dailycamera_wp_json_posts.json").read_text()
    seen, matched, queued = process_feed(
        db, "Daily Camera", raw_json, __import__("datetime").datetime.utcnow(), source_type="wp_json"
    )
    assert seen == 10
    mentions = db.query(NewsMention).filter(NewsMention.source_name == "Daily Camera").all()
    # Two real articles about the same real story in this fixture: the
    # bond-hike story and an earlier one about his Boulder County arrest.
    morphew = [m for m in mentions if "Morphew" in m.headline]
    assert len(morphew) == 2
    assert all(m.match_status == MatchStatus.unmatched_review for m in morphew)
    # headline HTML entities decoded, not left as raw markup
    assert all("&#8217;" not in m.headline for m in mentions)


# --- SYNTHETIC fixtures below: prove the positive-match path -----------------

_SYNTHETIC_CASE_NUMBER_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Synthetic Test Feed</title>
<item>
  <title>SYNTHETIC: Judge sets jury trial date in Dawson case</title>
  <link>https://example-test.invalid/synthetic-article-1</link>
  <description>Court records for case number 2026CR001452 show a jury trial has been scheduled.</description>
  <pubDate>Mon, 07 Sep 2026 12:00:00 GMT</pubDate>
</item>
</channel></rss>
"""

_SYNTHETIC_PARTY_NAME_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Synthetic Test Feed</title>
<item>
  <title>SYNTHETIC: Alex Dresden case draws attention ahead of trial</title>
  <link>https://example-test.invalid/synthetic-article-2</link>
  <description>Alex Dresden is scheduled to appear in Boulder County court next week.</description>
  <pubDate>Mon, 07 Sep 2026 12:00:00 GMT</pubDate>
</item>
</channel></rss>
"""


def test_synthetic_article_with_case_number_auto_matches(db, monkeypatch):
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    hearing = _make_hearing("2026CR001452", ["People", "Dawson"])
    db.add(hearing)
    db.commit()

    seen, matched, queued = process_feed(db, "Synthetic Test Feed", _SYNTHETIC_CASE_NUMBER_FEED,
                                          __import__("datetime").datetime.utcnow())
    assert (seen, matched, queued) == (1, 1, 0)

    mention = db.query(NewsMention).filter(NewsMention.article_url.contains("synthetic-article-1")).one()
    assert mention.match_status == MatchStatus.auto_matched
    assert mention.hearing_id == hearing.id
    assert hearing.has_news_mention is True


def test_synthetic_article_matches_via_party_name_when_no_case_number(db, monkeypatch):
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    hearing = _make_hearing("2026CR009999", ["People", "Alex Dresden"])
    db.add(hearing)
    db.commit()

    seen, matched, queued = process_feed(db, "Synthetic Test Feed", _SYNTHETIC_PARTY_NAME_FEED,
                                          __import__("datetime").datetime.utcnow())
    assert (seen, matched, queued) == (1, 1, 0)

    mention = db.query(NewsMention).filter(NewsMention.article_url.contains("synthetic-article-2")).one()
    assert mention.match_status == MatchStatus.auto_matched
    assert mention.hearing_id == hearing.id


def test_reprocessing_same_feed_does_not_duplicate_mentions(db, monkeypatch):
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    now = __import__("datetime").datetime.utcnow()
    process_feed(db, "Synthetic Test Feed", _SYNTHETIC_CASE_NUMBER_FEED, now)
    seen, matched, queued = process_feed(db, "Synthetic Test Feed", _SYNTHETIC_CASE_NUMBER_FEED, now)
    assert (seen, matched, queued) == (0, 0, 0)  # already-seen article_url is skipped
    assert db.query(NewsMention).count() == 1


def test_run_news_monitor_alerts_when_every_source_fails(db, monkeypatch):
    calls = []
    monkeypatch.setattr("app.jobs.news_monitor.alert_job_failure", lambda job, msg: calls.append((job, msg)))

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated parse failure")

    monkeypatch.setattr("app.jobs.news_monitor.process_feed", _boom)

    job = run_news_monitor(db, feed_texts={"Bad Source": "<rss></rss>"})
    assert job.success is False
    assert len(calls) == 1
    assert calls[0][0] == "news_monitor"


def test_run_news_monitor_with_fixture_feed_texts_end_to_end(db, monkeypatch):
    monkeypatch.setattr("app.jobs.news_monitor.fetch_article_text", lambda url: None)
    job = run_news_monitor(db, feed_texts={
        "Colorado Sun": (FIXTURES / "real_coloradosun_feed.xml").read_text(),
        "Synthetic Test Feed": _SYNTHETIC_CASE_NUMBER_FEED,
    })
    assert isinstance(job, JobRun)
    assert job.success is True
    assert job.rows_seen >= 2
