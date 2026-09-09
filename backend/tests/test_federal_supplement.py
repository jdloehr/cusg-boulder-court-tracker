"""
Live integration test against the real CourtListener free search API
(Section 2.3). Unlike coloradojudicial.gov, this endpoint IS reachable from
the build/CI network -- confirmed during build (see
docs/DATA_SOURCE_FINDINGS.md). This test hits the real API rather than a
fixture, to satisfy Section 12's "at least one working example of a federal
case pulled/matched via CourtListener" with genuine data, not a mock.

Skips gracefully (rather than failing the whole suite) if network access to
courtlistener.com is unavailable in whatever environment runs this later --
external-service flakiness shouldn't block an otherwise-green build, but a
real pass here is meaningful evidence the integration works.
"""
import httpx
import pytest

from app.jobs.federal_supplement import search_candidates


def _courtlistener_reachable() -> bool:
    try:
        r = httpx.get("https://www.courtlistener.com/api/rest/v4/search/",
                       params={"q": "test"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _courtlistener_reachable(), reason="courtlistener.com not reachable from this network")
def test_suncor_boulder_case_is_findable_via_real_courtlistener_search():
    """The Suncor Energy / Boulder County climate-liability case line
    (Section 2.3's worked example) genuinely exists in CourtListener's
    index -- this proves the search integration against live data, not a
    canned fixture."""
    candidates = search_candidates("Suncor Boulder", result_type="o")
    assert len(candidates) > 0
    assert any("suncor" in c.case_name.lower() and "boulder" in c.case_name.lower() for c in candidates)
    # Real result observed during build: "Boulder County Commissioners v.
    # Suncor Energy", Court of Appeals for the Tenth Circuit, filed 2022-02-08.
    top = candidates[0]
    assert top.absolute_url.startswith("https://www.courtlistener.com/opinion/")
