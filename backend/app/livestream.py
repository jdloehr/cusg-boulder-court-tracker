"""
Phase-2 doc, Section 2: livestream link defaults by court_location.

Built honestly, not as a "watch now" guarantee:
- State courts (county/district, and Colorado's own Supreme Court/Court of
  Appeals -- confirmed live, that same portal's "Livestream access" link on
  coloradojudicial.gov's oral-arguments pages points here too) share one
  real, confirmed-reachable portal: live.coloradojudicial.gov. It's a
  client-side county-picker with no discoverable deep-link query
  parameter (checked live during build -- the county dropdown is
  populated by client-side JS, not present in the page's initial HTML, so
  there's nothing honest to deep-link to yet). Link to the portal itself
  and tell the visitor to pick the county there, rather than fabricate an
  unverified URL parameter.
- Per Chief Justice Directive 23-02, there is NO presumptive livestreaming
  of trials and evidentiary hearings -- that's the judge's discretion.
  Other hearing types (arraignments, motions, oral arguments) are more
  commonly, but still not universally, streamed. A link existing here
  never means a stream is guaranteed to exist for a specific hearing.
- Federal district court: no general public video livestreaming. Whether
  a specific case has a published audio-access line is decided per-case,
  not something to default a URL for -- left `none`/blank unless a
  curator adds one when publishing (see PublishAppellateCandidateIn).
- U.S. Supreme Court: a real, standing live-audio page
  (supremecourt.gov/oral_arguments/live.aspx, confirmed reachable),
  provided for oral arguments since 2020.
"""
from __future__ import annotations

from app.models import CourtLocation, LivestreamSourceType

STATE_PORTAL_URL = "https://live.coloradojudicial.gov/"
SCOTUS_LIVE_AUDIO_URL = "https://www.supremecourt.gov/oral_arguments/live.aspx"

_STATE_COURTS = {
    CourtLocation.boulder_county,
    CourtLocation.boulder_district,
    CourtLocation.longmont_combined,
    CourtLocation.colorado_supreme_court,
    CourtLocation.colorado_court_of_appeals,
}


def default_livestream(court_location: CourtLocation) -> tuple[LivestreamSourceType, str | None]:
    """Returns (source_type, url) to assign a Hearing at creation time.
    Callers (docket_pull.py, routers/admin.py's appellate publish) can
    still override url for a specific case (e.g. a known federal
    audio-access line)."""
    if court_location in _STATE_COURTS:
        return LivestreamSourceType.state_portal, STATE_PORTAL_URL
    if court_location == CourtLocation.us_supreme_court:
        return LivestreamSourceType.scotus_audio, SCOTUS_LIVE_AUDIO_URL
    return LivestreamSourceType.none, None
