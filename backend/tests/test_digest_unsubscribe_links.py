"""
Oct 2026 review, Phase 1 item 1: every unsubscribe link app/jobs/digest.py
builds used to be a bare relative path ("/unsubscribe/<token>"), which
means nothing sitting in plain-text email body -- there's no browser
location to resolve it against -- and the frontend had no
/unsubscribe/:token route to land on either. Covers all three call
sites that build one.
"""
from app.jobs import digest
from app.models import Subscription, SubscriptionFilterType, SubscriptionFrequency


def _active_sub(**overrides):
    defaults = dict(
        email="watcher@example.com",
        filter_type=SubscriptionFilterType.hearing_type_category,
        filter_value="jury_trial",
        frequency=SubscriptionFrequency.weekly_digest,
        unsubscribe_token="tok-123",
        is_active=True,
    )
    defaults.update(overrides)
    return Subscription(**defaults)


def test_weekly_digest_unsubscribe_link_is_absolute(db, monkeypatch):
    monkeypatch.setattr(digest, "FRONTEND_URL", "https://cusg-boulder-court-tracker.vercel.app")
    db.add(_active_sub())
    db.commit()

    sent = []
    monkeypatch.setattr(digest, "send_email", lambda to, subject, body, **kw: sent.append((body, kw)))
    digest.run_weekly_digest(db)

    assert len(sent) == 1
    body, kwargs = sent[0]
    expected_url = "https://cusg-boulder-court-tracker.vercel.app/unsubscribe/tok-123"
    assert f"Unsubscribe: {expected_url}" in body
    assert kwargs["list_unsubscribe_url"] == expected_url


def test_weekly_digest_unsubscribe_link_falls_back_to_relative_path_locally(db, monkeypatch):
    """FRONTEND_URL is "" in local dev (app/config.py's own documented
    default) -- same bare-relative-path behavior as before this fix,
    not broken, just not clickable outside a browser already on this
    site (which is the pre-existing, accepted local-dev trade-off)."""
    monkeypatch.setattr(digest, "FRONTEND_URL", "")
    db.add(_active_sub())
    db.commit()

    sent = []
    monkeypatch.setattr(digest, "send_email", lambda to, subject, body, **kw: sent.append((body, kw)))
    digest.run_weekly_digest(db)

    body, kwargs = sent[0]
    assert "Unsubscribe: /unsubscribe/tok-123" in body
    assert kwargs["list_unsubscribe_url"] == "/unsubscribe/tok-123"


def test_realtime_case_change_unsubscribe_link_is_absolute(db, monkeypatch):
    from datetime import date

    from app.models import (
        AppearanceType, CaseCategory, CourtLocation, Hearing, HearingSource,
        HearingStatus, HearingTypeCategory,
    )

    monkeypatch.setattr(digest, "FRONTEND_URL", "https://cusg-boulder-court-tracker.vercel.app")
    hearing = Hearing(
        source=HearingSource.state_docket_export, case_number="2026CR999",
        case_category=CaseCategory.criminal, hearing_type_raw="Jury Trial",
        hearing_type_display="Jury Trial", hearing_type_category=HearingTypeCategory.jury_trial.value,
        date=date(2026, 11, 1), court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person, status=HearingStatus.changed,
    )
    sub = _active_sub(
        filter_type=SubscriptionFilterType.case_number, filter_value="2026CR999",
        frequency=SubscriptionFrequency.realtime_for_followed_case,
    )
    db.add_all([hearing, sub])
    db.commit()

    sent = []
    monkeypatch.setattr(digest, "send_email", lambda to, subject, body, **kw: sent.append((body, kw)))
    digest.notify_realtime_subscribers_of_change(db, hearing)

    body, kwargs = sent[0]
    expected_url = "https://cusg-boulder-court-tracker.vercel.app/unsubscribe/tok-123"
    assert expected_url in body
    assert kwargs["list_unsubscribe_url"] == expected_url
