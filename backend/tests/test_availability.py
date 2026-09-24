"""
Phase-6.2/6.3 docs: the Justice-only recurring-availability grid/meter/
heatmap and the matching newsletter opt-in. Phase 6.3 replaced the
original range-block representation with a fixed weekly grid of 30-min
slots (7:00 AM-8:00 PM, 26 slots) -- this file covers:
- app/availability.py's pure functions (time/duration parsing, the fixed
  grid window, slot-overlap logic).
- app/availability_slots.py's DB-backed load/replace helpers.
- The Justice-only /me/availability endpoints, the batched
  /hearings/availability-summary meter endpoint, and the new
  /justices/team/availability heatmap -- all gated to real Justices and
  never leaking into the public JusticeOut shape.
- The digest job's personal_availability branch.
- SubscriptionCreate's availability_cells validation.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from app.auth import hash_password
from app.availability import (
    NUM_SLOTS,
    SLOT_WINDOW_START_MIN,
    hearing_matches_slots,
    hearing_overlapping_slots,
    parse_duration_minutes,
    parse_hearing_time,
    weekday_abbr,
)
from app.availability_slots import load_free_slots_by_day, load_owner_cells, replace_owner_slots
from app.db import get_db
from app.jobs.digest import hearings_matching_subscription
from app.main import app
from app.models import (
    AdminUser,
    AppearanceType,
    AvailabilityOwnerType,
    AvailabilitySlot,
    Base,
    CaseCategory,
    CourtLocation,
    DayOfWeek,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    Subscription,
    SubscriptionFilterType,
    SubscriptionFrequency,
)
from app.rate_limit import reset_for_tests

# --- Pure-function tests: no DB/client needed ------------------------------


def test_parse_hearing_time_handles_the_formats_seen_in_real_docket_data():
    assert parse_hearing_time("9:00 AM") == 9 * 60
    assert parse_hearing_time("1:30 PM") == 13 * 60 + 30
    assert parse_hearing_time("14:00") == 14 * 60
    assert parse_hearing_time("") is None
    assert parse_hearing_time(None) is None
    assert parse_hearing_time("not a time") is None


def test_parse_duration_minutes_matches_real_fixture_values():
    assert parse_duration_minutes("2 hours") == 120
    assert parse_duration_minutes("30 minutes") == 30
    assert parse_duration_minutes("1 hour") == 60
    assert parse_duration_minutes("45 minutes") == 45
    assert parse_duration_minutes("1 day") == 24 * 60
    assert parse_duration_minutes("1 hour 30 minutes") == 90


def test_parse_duration_minutes_falls_back_to_the_documented_default():
    assert parse_duration_minutes(None) == 60
    assert parse_duration_minutes("") == 60
    assert parse_duration_minutes("unknown") == 60


def test_weekday_abbr_matches_python_date_weekday():
    assert weekday_abbr(date(2026, 9, 21)) == "mon"  # a known Monday
    assert weekday_abbr(date(2026, 9, 27)) == "sun"


def test_grid_window_is_7am_to_8pm_in_26_slots():
    # Real production evidence (75 real hearings start at exactly 7:00 AM)
    # is why this window starts at 7am, not the doc's illustrative 8am.
    assert SLOT_WINDOW_START_MIN == 7 * 60
    assert NUM_SLOTS == 26


def test_hearing_overlapping_slots_finds_the_right_slot_indices():
    # 7:00-7:30 AM is slot 0; a 9:00 AM hearing is slot index 4.
    assert hearing_overlapping_slots(7 * 60, 7 * 60 + 30) == {0}
    assert hearing_overlapping_slots(9 * 60, 9 * 60 + 30) == {4}
    # A 2-hour hearing spans 4 consecutive 30-min slots.
    assert hearing_overlapping_slots(9 * 60, 9 * 60 + 120) == {4, 5, 6, 7}


def test_hearing_matches_slots_requires_same_day_and_overlap():
    free = {"mon": {4, 5}}  # 9:00 AM - 10:00 AM on Monday
    assert hearing_matches_slots(date(2026, 9, 21), "9:00 AM", "1 hour", free) is True
    # Tuesday -- wrong day entirely.
    assert hearing_matches_slots(date(2026, 9, 22), "9:00 AM", "1 hour", free) is False
    # Monday, but starts well after the free slots end.
    assert hearing_matches_slots(date(2026, 9, 21), "1:00 PM", "1 hour", free) is False
    # Partial overlap still counts ("full-duration overlap not required").
    assert hearing_matches_slots(date(2026, 9, 21), "9:45 AM", "2 hours", free) is True


def test_hearing_matches_slots_never_matches_an_unparseable_time():
    free = {"mon": {4, 5}}
    assert hearing_matches_slots(date(2026, 9, 21), "", "1 hour", free) is False
    assert hearing_matches_slots(date(2026, 9, 21), None, "1 hour", free) is False


def test_hearing_outside_grid_window_never_matches():
    # The accepted trade-off of a bounded 7am-8pm grid: real production
    # outliers (a handful of "1:00 AM" docket-parsing-noise entries, one
    # real 8:15 PM hearing) fall entirely outside the window and can never
    # match anyone's painted-free slots, Justice or visitor.
    free_all_day = {"mon": set(range(NUM_SLOTS))}  # every slot marked free
    assert hearing_matches_slots(date(2026, 9, 21), "1:00 AM", "1 hour", free_all_day) is False
    assert hearing_matches_slots(date(2026, 9, 21), "8:15 PM", "1 hour", free_all_day) is False


# --- Endpoint tests ----------------------------------------------------------


@pytest.fixture()
def client():
    reset_for_tests()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    seed = TestSession()
    # Relative to today, not hardcoded -- default_upcoming_hearings only
    # looks at the next 14 days, and a fixed past date would silently drop
    # out of every query as real time passes (the exact bug fixed in
    # test_hearing_sorting.py/test_docket_pull.py during Phase 6).
    first_date = date.today() + timedelta(days=1)
    second_date = first_date + timedelta(days=1)
    hearing_a = Hearing(
        id="hearing-a", source=HearingSource.state_docket_export, case_number="2026CR000123",
        case_category=CaseCategory.criminal, hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=first_date, time="9:00 AM",
        duration="2 hours", court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person, status=HearingStatus.scheduled,
    )
    hearing_b = Hearing(
        id="hearing-b", source=HearingSource.state_docket_export, case_number="2026CR000456",
        case_category=CaseCategory.criminal, hearing_type_raw="Motions Hearing", hearing_type_display="Motions Hearing",
        hearing_type_category=HearingTypeCategory.other.value, date=second_date, time="1:00 PM",
        duration="1 hour", court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person, status=HearingStatus.scheduled,
    )
    dillon = AdminUser(email="dillon@test.local", hashed_password=hash_password("pw"),
                        is_justice=True, is_active=True, display_name="Dillon Rankin")
    joshua = AdminUser(email="joshua@test.local", hashed_password=hash_password("pw"),
                        is_justice=True, is_active=True, display_name="Joshua Loehr")
    non_justice = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"), role=None)
    seed.add_all([hearing_a, hearing_b, dillon, joshua, non_justice])
    seed.commit()
    seed.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(client, email):
    r = client.post("/api/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _first_hearing_day_abbr() -> str:
    return weekday_abbr(date.today() + timedelta(days=1))


def _slot_index_for_9am() -> int:
    return (9 * 60 - SLOT_WINDOW_START_MIN) // 30


# --- app/availability_slots.py helpers --------------------------------------


def test_availability_slot_unique_constraint_rejects_a_duplicate_cell():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    db.add(AvailabilitySlot(owner_type=AvailabilityOwnerType.justice, owner_id="j1",
                             day_of_week=DayOfWeek.mon, slot_index=4))
    db.commit()
    db.add(AvailabilitySlot(owner_type=AvailabilityOwnerType.justice, owner_id="j1",
                             day_of_week=DayOfWeek.mon, slot_index=4))
    with pytest.raises(IntegrityError):
        db.commit()
    db.close()


def test_replace_owner_slots_is_a_full_replace():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()

    class _Cell:
        def __init__(self, day_of_week, slot_index):
            self.day_of_week = day_of_week
            self.slot_index = slot_index

    replace_owner_slots(db, AvailabilityOwnerType.justice, "j1", [_Cell("mon", 4), _Cell("wed", 5)])
    db.commit()
    assert len(load_owner_cells(db, AvailabilityOwnerType.justice, "j1")) == 2

    replace_owner_slots(db, AvailabilityOwnerType.justice, "j1", [_Cell("fri", 10)])
    db.commit()
    cells = load_owner_cells(db, AvailabilityOwnerType.justice, "j1")
    assert cells == [{"day_of_week": "fri", "slot_index": 10}]
    db.close()


# --- Justice availability endpoints -----------------------------------------


def test_availability_endpoints_require_a_justice_login(client):
    r = client.get("/api/justices/me/availability")
    assert r.status_code == 401

    non_justice_headers = _auth(client, "editor@test.local")
    r2 = client.get("/api/justices/me/availability", headers=non_justice_headers)
    assert r2.status_code == 403


def test_a_justice_can_set_and_read_back_their_own_availability(client):
    headers = _auth(client, "dillon@test.local")
    cells = [{"day_of_week": "mon", "slot_index": 4}]

    r = client.patch("/api/justices/me/availability", json={"cells": cells}, headers=headers)
    assert r.status_code == 200
    assert r.json()["cells"] == cells

    r2 = client.get("/api/justices/me/availability", headers=headers)
    assert r2.json()["cells"] == cells


def test_updating_availability_is_a_full_replace_not_incremental(client):
    headers = _auth(client, "dillon@test.local")
    client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "mon", "slot_index": 4}]},
                  headers=headers)
    r = client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "wed", "slot_index": 10}]},
                      headers=headers)
    assert r.json()["cells"] == [{"day_of_week": "wed", "slot_index": 10}]

    # The old Monday row is actually gone, not just superseded in the response --
    # a real regression the old JSON blob couldn't even represent.
    r2 = client.get("/api/justices/me/availability", headers=headers)
    assert r2.json()["cells"] == [{"day_of_week": "wed", "slot_index": 10}]


def test_availability_cell_slot_index_is_bounds_checked(client):
    headers = _auth(client, "dillon@test.local")
    r = client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "mon", "slot_index": 26}]},
                      headers=headers)
    assert r.status_code == 422
    r2 = client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "mon", "slot_index": -1}]},
                       headers=headers)
    assert r2.status_code == 422


def test_availability_never_appears_on_the_public_justice_endpoints(client):
    headers = _auth(client, "dillon@test.local")
    client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "mon", "slot_index": 4}]},
                  headers=headers)

    roster = client.get("/api/justices").json()
    dillon_row = next(j for j in roster if j["display_name"] == "Dillon Rankin")
    assert "availability_cells" not in dillon_row
    assert "availability" not in dillon_row

    profile = client.get(f"/api/justices/{dillon_row['id']}").json()
    assert "availability_cells" not in profile
    assert "availability" not in profile


# --- Per-hearing meter --------------------------------------------------------


def test_availability_summary_requires_a_justice_login(client):
    r = client.post("/api/hearings/availability-summary", json={"hearing_ids": ["hearing-a"]})
    assert r.status_code == 401

    non_justice_headers = _auth(client, "editor@test.local")
    r2 = client.post("/api/hearings/availability-summary", json={"hearing_ids": ["hearing-a"]},
                      headers=non_justice_headers)
    assert r2.status_code == 403


def test_availability_summary_computes_free_count_and_names(client):
    dillon_headers = _auth(client, "dillon@test.local")
    joshua_headers = _auth(client, "joshua@test.local")
    client.patch("/api/justices/me/availability",
                  json={"cells": [{"day_of_week": _first_hearing_day_abbr(), "slot_index": _slot_index_for_9am()}]},
                  headers=dillon_headers)
    # Joshua has no availability set at all -- should count as not free anywhere.

    r = client.post("/api/hearings/availability-summary",
                     json={"hearing_ids": ["hearing-a", "hearing-b"]}, headers=joshua_headers)
    assert r.status_code == 200
    body = r.json()

    assert body["hearing-a"]["total"] == 2
    assert body["hearing-a"]["free_count"] == 1
    assert body["hearing-a"]["free_justice_names"] == ["Dillon Rankin"]
    assert body["hearing-a"]["time_known"] is True

    assert body["hearing-b"]["free_count"] == 0
    assert body["hearing-b"]["free_justice_names"] == []


def test_availability_summary_only_returns_requested_hearing_ids(client):
    headers = _auth(client, "dillon@test.local")
    r = client.post("/api/hearings/availability-summary", json={"hearing_ids": ["hearing-a"]}, headers=headers)
    assert set(r.json().keys()) == {"hearing-a"}


# --- Team Availability heatmap ------------------------------------------------


def test_team_availability_requires_a_justice_login(client):
    r = client.get("/api/justices/team/availability")
    assert r.status_code == 401

    non_justice_headers = _auth(client, "editor@test.local")
    r2 = client.get("/api/justices/team/availability", headers=non_justice_headers)
    assert r2.status_code == 403


def test_team_availability_aggregates_across_justices(client):
    dillon_headers = _auth(client, "dillon@test.local")
    joshua_headers = _auth(client, "joshua@test.local")
    client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "mon", "slot_index": 4}]},
                  headers=dillon_headers)
    client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "mon", "slot_index": 4}]},
                  headers=joshua_headers)

    r = client.get("/api/justices/team/availability", headers=dillon_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_justices"] == 2
    assert len(body["cells"]) == 7 * NUM_SLOTS  # every grid cell, precomputed

    mon_slot_4 = next(c for c in body["cells"] if c["day_of_week"] == "mon" and c["slot_index"] == 4)
    assert mon_slot_4["free_count"] == 2
    assert set(mon_slot_4["free_justice_names"]) == {"Dillon Rankin", "Joshua Loehr"}

    mon_slot_5 = next(c for c in body["cells"] if c["day_of_week"] == "mon" and c["slot_index"] == 5)
    assert mon_slot_5["free_count"] == 0


# --- Digest job's personal_availability branch ------------------------------


def test_digest_personal_availability_branch_filters_to_overlapping_hearings(client):
    # Reuse the same in-memory DB the fixture already wired up via the
    # dependency override, rather than standing up a second engine.
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        sub = Subscription(
            email="watcher@example.com",
            filter_type=SubscriptionFilterType.personal_availability,
            filter_value="n/a",
            frequency=SubscriptionFrequency.weekly_digest,
        )
        db.add(sub)
        db.flush()
        db.add(AvailabilitySlot(owner_type=AvailabilityOwnerType.personal_subscription, owner_id=sub.id,
                                 day_of_week=DayOfWeek(_first_hearing_day_abbr()), slot_index=_slot_index_for_9am()))
        db.commit()
        db.refresh(sub)

        matching = hearings_matching_subscription(db, sub)
        assert {h.id for h in matching} == {"hearing-a"}
    finally:
        gen.close()


# --- SubscriptionCreate's availability_cells validation ---------------------


def test_subscribing_with_personal_availability_requires_cells(client):
    r = client.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "personal_availability",
        "filter_value": "n/a", "frequency": "weekly_digest",
    })
    assert r.status_code == 422


def test_subscribing_with_personal_availability_and_cells_succeeds(client):
    cells = [{"day_of_week": "mon", "slot_index": 4}]
    r = client.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "personal_availability",
        "filter_value": "n/a", "frequency": "weekly_digest", "availability_cells": cells,
    })
    assert r.status_code == 200, r.text
    assert r.json()["availability_cells"] == cells


def test_availability_cells_rejected_for_a_non_personal_filter_type(client):
    r = client.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
        "availability_cells": [{"day_of_week": "mon", "slot_index": 4}],
    })
    assert r.status_code == 422
