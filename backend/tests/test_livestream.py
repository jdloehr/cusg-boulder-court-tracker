from app.livestream import SCOTUS_LIVE_AUDIO_URL, STATE_PORTAL_URL, default_livestream
from app.models import CourtLocation, LivestreamSourceType


def test_state_courts_default_to_the_real_state_portal():
    for loc in (
        CourtLocation.boulder_county,
        CourtLocation.boulder_district,
        CourtLocation.longmont_combined,
        CourtLocation.colorado_supreme_court,
        CourtLocation.colorado_court_of_appeals,
    ):
        source_type, url = default_livestream(loc)
        assert source_type == LivestreamSourceType.state_portal
        assert url == STATE_PORTAL_URL


def test_scotus_defaults_to_the_real_live_audio_page():
    source_type, url = default_livestream(CourtLocation.us_supreme_court)
    assert source_type == LivestreamSourceType.scotus_audio
    assert url == SCOTUS_LIVE_AUDIO_URL


def test_federal_district_has_no_default_url():
    # No general public video livestreaming for federal district court --
    # a specific audio-access line is a per-case curator override, not a
    # default (see PublishAppellateCandidateIn.federal_audio_line_url).
    source_type, url = default_livestream(CourtLocation.us_district_colorado)
    assert source_type == LivestreamSourceType.none
    assert url is None


def test_unknown_location_has_no_default_url():
    source_type, url = default_livestream(CourtLocation.unknown)
    assert source_type == LivestreamSourceType.none
    assert url is None
