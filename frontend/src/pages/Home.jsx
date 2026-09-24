import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import ColonnadeMotif from "../components/ColonnadeMotif.jsx";
import { CASE_CATEGORY_LABELS, COURT_LOCATION_LABELS } from "../courtInfo.js";
import { firstSentence } from "../textUtils.js";

// Phase-6.2 doc, Section 3: the approved homepage design -- a distinct
// marketing/landing page at "/", separate from the filterable docket
// (moved to /hearings). Built last, once Sections 4-6's hearing-card
// indicators (recommendation star, availability meter, "fits your
// schedule" badge) all exist, so the spotlight card's star can be
// verified alongside them per the doc's own open item 3.
export default function Home() {
  const [hearings, setHearings] = useState(null);
  const [recommendedHearingIds, setRecommendedHearingIds] = useState(new Set());

  useEffect(() => {
    api.listHearings({}).then(setHearings).catch(() => setHearings([]));
    api
      .listRecommendations()
      .then((recs) => setRecommendedHearingIds(new Set(recs.map((r) => r.hearing_id))))
      .catch(() => {
        /* non-critical -- the pick still renders fine without a star */
      });
  }, []);

  // "This Week's Pick": the soonest upcoming hearing with a curated
  // blurb (an Editor already decided it's worth highlighting), falling
  // back to the soonest upcoming hearing overall if none has one yet.
  // `hearings` is already sorted chronologically by GET /api/hearings.
  const pick = hearings ? hearings.find((h) => h.curated_blurb) || hearings[0] : null;
  const weeklyList = hearings ? hearings.slice(0, 8) : [];

  return (
    <>
      <section className="hero">
        <ColonnadeMotif />
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="hero-eyebrow">A Project of the CUSG Judicial Branch</p>
            <h1 className="hero-headline">Watch Colorado law happen.</h1>
            <p className="hero-intro">
              Every week, real jury trials and oral arguments happen a short walk from campus.
              This tool is meant to connect{" "}
              <strong style={{ color: "var(--accent)" }}>
                anyone curious about helping others through law
              </strong>{" "}
              with the resources to get in a courtroom and begin their journey.
            </p>
            <div className="hero-actions">
              <Link to="/hearings" className="btn btn-navy">
                Browse This Week's Docket
              </Link>
              <Link to="/subscribe" className="btn btn-secondary">
                Get the Weekly Digest
              </Link>
            </div>
          </div>

          <div className="hero-spotlight-wrap">
            {pick && (
              <div className="card hero-spotlight">
                <p className="hero-spotlight-label">This Week's Pick</p>
                {recommendedHearingIds.has(pick.id) && (
                  <span className="badge badge-news" style={{ marginBottom: "0.5rem", display: "inline-block" }}>
                    &#9733; Justice-Recommended
                  </span>
                )}
                <h3 style={{ marginTop: 0 }}>{firstSentence(pick.hearing_type_display)}</h3>
                <p style={{ margin: "0.2rem 0", color: "var(--ink-soft)", fontSize: "0.9rem" }}>
                  {pick.date} &middot; {pick.time || "Time TBD"}
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

      <div className="pull-quote">
        <p>
          &ldquo;Tell me and I forget. Teach me and I remember. Involve me and I learn.&rdquo;
        </p>
      </div>

      <section>
        <h2>Get Started in Boulder Courts</h2>
        <table className="schedule">
          <tbody>
            {weeklyList.map((h) => (
              <tr key={h.id}>
                <td style={{ whiteSpace: "nowrap", color: "var(--ink-soft)", fontSize: "0.85rem" }}>{h.date}</td>
                <td>
                  <span className="badge badge-category">{firstSentence(h.hearing_type_display)}</span>
                </td>
                <td>
                  <Link to={`/hearings/${h.id}`}>{h.case_number}</Link>
                </td>
                <td style={{ color: "var(--ink-soft)", fontSize: "0.85rem" }}>
                  {h.courtroom ? `Courtroom ${h.courtroom}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          <Link to="/hearings">View the full calendar &rarr;</Link>
        </p>
      </section>

      <section className="about-band-wrap">
        <div className="about-band">
          <h2>About this project.</h2>
          <p>
            The CUSG Boulder Court Tracker is built and maintained by the CUSG Judicial Branch to
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
