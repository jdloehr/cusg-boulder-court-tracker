import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";

// Phase-6.2 doc, Section 1: replaces the old click-through directory
// (a grid of circular photos, each linking to its own /justices/:id
// page) with a single, unified page listing every Justice's full
// profile inline, alternating photo side per entry. Names linked from
// elsewhere on the site (see components/JusticeLink.jsx) now jump to
// an anchor on this page instead of a separate URL.
export default function Justices() {
  const [justices, setJustices] = useState(null);
  const [error, setError] = useState(null);
  const location = useLocation();

  useEffect(() => {
    api.listJustices().then(setJustices).catch((e) => setError(e.message));
  }, []);

  // React Router doesn't scroll to a #fragment on its own for a
  // same-app navigation (only a full page load does) -- without this,
  // clicking a JusticeLink from another page lands at the top of
  // /justices instead of at that Justice's section.
  useEffect(() => {
    if (!justices || !location.hash) return;
    const el = document.getElementById(location.hash.slice(1));
    if (el) el.scrollIntoView();
  }, [justices, location.hash]);

  if (error) return <p className="message-error">{error}</p>;
  if (!justices) return <p>Loading&hellip;</p>;

  const admin = getStoredAdmin();

  return (
    <article>
      <h1>Meet the Justices</h1>
      <p className="disclaimer">The CUSG Court's current roster.</p>

      {justices.map((j, index) => {
        const isMe = admin?.isJustice && admin.id === j.id;
        return (
          <section
            id={`justice-${j.id}`}
            key={j.id}
            className={`justice-entry ${index % 2 === 1 ? "justice-entry-reverse" : ""}`}
          >
            <div className="justice-entry-photo">
              {j.photo_url ? (
                <img className="justice-photo-square" src={api.justicePhotoUrl(j.id)} alt="" />
              ) : (
                <div className="justice-photo-square justice-photo-placeholder" aria-hidden="true">
                  {(j.display_name || "?")[0]}
                </div>
              )}
            </div>
            <div className="justice-entry-info">
              <h2 style={{ marginBottom: "0.2rem" }}>{j.display_name}</h2>
              {j.title && <p style={{ color: "var(--ink-soft)", marginTop: 0 }}>{j.title}</p>}
              {j.year_or_major && <p style={{ marginTop: "0.2rem" }}>{j.year_or_major}</p>}
              {isMe && (
                <p style={{ marginTop: "0.5rem" }}>
                  <Link to="/justices/me/edit" className="btn btn-secondary">
                    Edit my profile
                  </Link>
                </p>
              )}

              {j.bio && (
                <div className="card">
                  <h3>Bio</h3>
                  <p className="blurb">{j.bio}</p>
                </div>
              )}
              {j.why_care && (
                <div className="card">
                  <h3>Why I care about court-watching</h3>
                  <p className="blurb">{j.why_care}</p>
                </div>
              )}
              {j.fun_fact && (
                <div className="card">
                  <h3>Fun fact</h3>
                  <p className="blurb">{j.fun_fact}</p>
                </div>
              )}
              {!j.bio && !j.why_care && !j.fun_fact && (
                <p style={{ color: "var(--ink-soft)" }}>This Justice hasn't filled out their profile yet.</p>
              )}
            </div>
          </section>
        );
      })}
    </article>
  );
}
