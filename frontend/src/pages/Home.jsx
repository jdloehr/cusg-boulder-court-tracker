import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import CourtPassportMark from "../components/CourtPassportMark.jsx";
import HearingTypeTag from "../components/HearingTypeTag.jsx";
import MountainStrip from "../components/MountainStrip.jsx";
import StampMotif from "../components/StampMotif.jsx";
import { CASE_CATEGORY_LABELS, COURT_LOCATION_LABELS } from "../courtInfo.js";
import { SITE_BYLINE, SITE_NAME } from "../site.js";
import { caseName, firstSentence, formatHearingDate } from "../textUtils.js";

// Phase-6.2 doc, Section 3: the approved homepage design -- a distinct
// marketing/landing page at "/", separate from the filterable docket
// (moved to /hearings). Built last, once Sections 4-6's hearing-card
// indicators (recommendation star, availability meter, "fits your
// schedule" badge) all exist, so the spotlight card's star can be
// verified alongside them per the doc's own open item 3.
export default function Home() {
  const [hearings, setHearings] = useState(null);
  const [pick, setPick] = useState(null);
  const [recommendedHearingIds, setRecommendedHearingIds] = useState(new Set());

  useEffect(() => {
    api.listHearings({}).then(setHearings).catch(() => setHearings([]));
    // Oct 2026 review, Phase 2 item 2: real bug -- this used to search
    // only the `hearings` list above (the default GET /api/hearings
    // view: in-person, next 14 days only) for is_weekly_pick, so an
    // Editor's real pick on a remote hearing or one further out
    // silently vanished from that search and the page fell back to a
    // heuristic (soonest hearing with a blurb) under the exact same
    // "This Week's Pick" label -- showing something nobody actually
    // picked, with no sign it wasn't the real pick. GET /api/hearings/
    // weekly-pick searches every hearing directly instead, and a null
    // result now means no card at all, not a heuristic standing in
    // under the same label.
    api.getWeeklyPick().then(setPick).catch(() => setPick(null));
    api
      .listRecommendations()
      .then((recs) => setRecommendedHearingIds(new Set(recs.map((r) => r.hearing_id))))
      .catch(() => {
        /* non-critical -- the pick still renders fine without a star */
      });
  }, []);

  const weeklyList = hearings ? hearings.slice(0, 8) : [];

  return (
    <>
      <section className="hero">
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="hero-eyebrow">
              <CourtPassportMark size={24} />
              {SITE_BYLINE}
            </p>
            <h1 className="hero-headline">Watch Colorado law happen.</h1>
            <p className="hero-intro">
              Every week, real jury trials and oral arguments happen a short bus or bike ride from
              campus.
              This tool is meant to connect{" "}
              <strong style={{ color: "var(--accent)" }}>
                anyone curious about helping others through law
              </strong>{" "}
              with the resources to get in a courtroom and begin their journey.
            </p>
            <div className="hero-actions">
              <Link to="/hearings" className="btn">
                Browse the Calendar
              </Link>
              <Link to="/subscribe" className="btn btn-secondary">
                Get the Weekly Digest
              </Link>
            </div>
          </div>

          <div className="hero-spotlight-wrap">
            <StampMotif
              size={110}
              color="var(--terracotta-deep)"
              line1="OPEN"
              line2="COURT"
              rotation={-14}
              className="hero-stamp"
            />
            {pick && (
              <div className="card hero-spotlight">
                <p className="hero-spotlight-label">This Week's Pick</p>
                {recommendedHearingIds.has(pick.id) && (
                  <span className="badge badge-news" style={{ marginBottom: "0.5rem", display: "inline-block" }}>
                    &#9733; Justice-Recommended
                  </span>
                )}
                {/* Oct 2026 review, Phase 4 item 4: the case name
                    leads, same as the hearing detail page's own <h1>
                    (textUtils.js::caseName) -- falls back to the
                    hearing type when no parties were parsed. */}
                <h3 style={{ marginTop: 0 }}>{caseName(pick) || firstSentence(pick.hearing_type_display)}</h3>
                {caseName(pick) && (
                  <p style={{ margin: "0 0 0.2rem", color: "var(--ink-soft)", fontSize: "0.85rem" }}>
                    {firstSentence(pick.hearing_type_display)}
                  </p>
                )}
                <p style={{ margin: "0.2rem 0", color: "var(--ink-soft)", fontSize: "0.9rem" }}>
                  {formatHearingDate(pick.date)} &middot; {pick.time || "Time TBD"}
                  {pick.duration ? ` (${pick.duration})` : ""}
                </p>
                <p style={{ margin: "0.2rem 0", color: "var(--ink-soft)", fontSize: "0.9rem" }}>
                  {COURT_LOCATION_LABELS[pick.court_location] || pick.court_location}
                </p>
                <p style={{ margin: "0.2rem 0", color: "var(--ink-soft)", fontSize: "0.9rem" }}>
                  Case {pick.case_number} &middot; {CASE_CATEGORY_LABELS[pick.case_category] || pick.case_category}
                </p>
                {pick.curated_blurb && <p className="blurb" style={{ marginTop: "0.75rem" }}>{pick.curated_blurb}</p>}
                <p style={{ marginTop: "0.75rem" }}>
                  <Link to={`/hearings/${pick.id}`}>See full details</Link>
                  {" · "}
                  <a href={api.icsUrl(pick.id)}>Add to calendar</a>
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Court Passport redesign: 3 full-bleed color blocks (terracotta
          deep / gold / sage), same "how it works" 3-step copy as before,
          large faint numerals -- the mockups' one decorative use of
          numerals, nowhere else. */}
      <section className="how-it-works">
        <div className="how-it-works-step how-it-works-step-1">
          <span className="how-it-works-numeral" aria-hidden="true">1</span>
          <h2>Find a hearing</h2>
          <p>Pick one from the docket, or start with a Justice's recommendation.</p>
        </div>
        <div className="how-it-works-step how-it-works-step-2">
          <span className="how-it-works-numeral" aria-hidden="true">2</span>
          <h2>Go watch</h2>
          <p>Most courtrooms are open to the public. Show up early and bring a notebook.</p>
        </div>
        <div className="how-it-works-step how-it-works-step-3">
          <span className="how-it-works-numeral" aria-hidden="true">3</span>
          <h2>Write it up</h2>
          <p>Mark that you went and add what you saw to the Archive.</p>
        </div>
      </section>

      <section className="pull-quote-band">
        <blockquote>
          &ldquo;Tell me and I forget. Teach me and I remember. Involve me and I learn.&rdquo;
        </blockquote>
        <MountainStrip backColor="#6E5679" slab1Color="#8B6F97" slab2Color="#A38AAE" slab3Color="#7B6286" />
      </section>

      <section>
        <h2>Get Started in Boulder Courts</h2>
        <p className="scroll-x-hint">Scroll to see every column &rarr;</p>
        <div className="scroll-x-wrap">
          <table className="schedule">
            <tbody>
              {weeklyList.map((h) => (
                <tr key={h.id}>
                  {/* Oct 2026 review, Phase 4 item 5: shared date
                      formatter instead of the raw ISO string. */}
                  <td style={{ whiteSpace: "nowrap", color: "var(--ink-soft)", fontSize: "0.85rem" }}>
                    {formatHearingDate(h.date)}
                  </td>
                  <td>
                    <HearingTypeTag label={firstSentence(h.hearing_type_display)} color={h.tag_color} hearingId={h.id} />
                  </td>
                  <td>
                    {/* Item 4: the case name leads; the case number
                        stays visible underneath for anyone checking
                        the official docket. */}
                    <Link to={`/hearings/${h.id}`}>{caseName(h) || h.case_number}</Link>
                    {caseName(h) && (
                      <div style={{ fontSize: "0.78rem", color: "var(--ink-soft)" }}>Case {h.case_number}</div>
                    )}
                  </td>
                  {/* Item 6: time + courthouse (Boulder vs. Longmont),
                      not the bare courtroom letter, which meant
                      nothing without already knowing which building. */}
                  <td style={{ color: "var(--ink-soft)", fontSize: "0.85rem", whiteSpace: "nowrap" }}>
                    {h.time || "Time TBD"} &middot; {COURT_LOCATION_LABELS[h.court_location] || h.court_location}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          <Link to="/hearings">View the full calendar &rarr;</Link>
        </p>
      </section>

      <section className="about-band-wrap">
        <div className="about-band">
          <h2>About {SITE_NAME}</h2>
          <p>
            {SITE_NAME} is built and maintained by the University of Colorado Judicial Branch to
            make it easier for students to find real court proceedings worth attending in person.
            Every listing pulls directly from Colorado's public docket, gets checked against local
            news coverage, and is reviewed by a small student team who also go watch, mark
            attendance, and write up what they saw in the Archive. If you're curious about the law
            and want to see it in session rather than just read about it, this is built for you.
          </p>
        </div>
      </section>
    </>
  );
}
