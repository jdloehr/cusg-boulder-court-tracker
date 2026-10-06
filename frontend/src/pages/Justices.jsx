import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";

// Meet the Justices redesign: cycles through the Archive page's
// existing accent set (not a second, competing color system) so two
// adjacent Justices never share a color. "ochre" is this redesign's
// "gold" -- same variable, no new one needed.
const ACCENT_CYCLE = ["terracotta", "sage", "ochre", "plum"];

function reducedMotionPreferred() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

// Phase-6.2 doc, Section 1: replaces the old click-through directory
// (a grid of circular photos, each linking to its own /justices/:id
// page) with a single, unified page listing every Justice's full
// profile inline, alternating photo side per entry. Names linked from
// elsewhere on the site (see components/JusticeLink.jsx) now jump to
// an anchor on this page instead of a separate URL.
export default function Justices() {
  const [justices, setJustices] = useState(null);
  const [error, setError] = useState(null);
  const [revealedIds, setRevealedIds] = useState(() => new Set());
  const [reduceMotion] = useState(reducedMotionPreferred);
  const location = useLocation();
  const sectionRefs = useRef(new Map());

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

  // Each section slides in from its own side with a fade as it
  // scrolls into view, once, via a single shared IntersectionObserver
  // rather than one per section. The first section is treated as
  // already revealed at render time (see isFirst below) instead of
  // through the observer, since it's usually already above the fold
  // on load -- first paint should never wait on a scroll event that
  // may never come, and it's never even observed. A visitor who's
  // asked for less motion is handled the same way, at render time
  // (see the reduceMotion check below) -- no observer is created, and
  // revealedIds never needs to be touched at all in that case.
  useEffect(() => {
    if (!justices || justices.length === 0 || reduceMotion || typeof IntersectionObserver === "undefined") return;
    const firstId = justices[0].id;

    const observer = new IntersectionObserver(
      (entries) => {
        const justRevealed = entries.filter((entry) => entry.isIntersecting);
        if (justRevealed.length === 0) return;
        setRevealedIds((prev) => {
          const next = new Set(prev);
          for (const entry of justRevealed) next.add(entry.target.dataset.justiceId);
          return next;
        });
        for (const entry of justRevealed) observer.unobserve(entry.target);
      },
      { threshold: 0.15 }
    );
    for (const [id, el] of sectionRefs.current) {
      if (id !== firstId && el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [justices, reduceMotion]);

  if (error) return <p className="message-error">{error}</p>;
  if (!justices) return <p>Loading&hellip;</p>;

  const admin = getStoredAdmin();

  return (
    <article>
      <h1>Meet the Justices</h1>
      <p className="disclaimer">CUSG Justices (student government), the current roster.</p>

      {justices.map((j, index) => {
        const isMe = admin?.isJustice && admin.id === j.id;
        const accent = ACCENT_CYCLE[index % ACCENT_CYCLE.length];
        const isFirst = index === 0;
        // The first section is always revealed -- it's usually already
        // above the fold on load, so first paint never waits on a
        // scroll event that may never come. Reduced motion means
        // everything is shown already, with no slide or fade at all.
        const revealed = isFirst || reduceMotion || revealedIds.has(j.id);
        const interests = (j.fun_fact || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        const hasAnyContent = j.bio || j.why_care || j.year_or_major || interests.length > 0;

        return (
          <section
            id={`justice-${j.id}`}
            key={j.id}
            ref={(el) => {
              if (el) sectionRefs.current.set(j.id, el);
            }}
            data-justice-id={j.id}
            className={`justice-entry ${index % 2 === 1 ? "justice-entry-reverse" : ""} ${revealed ? "revealed" : ""}`}
          >
            <div className="justice-photo-frame">
              <div className={`justice-photo-block justice-photo-block-${accent}`} aria-hidden="true" />
              {j.photo_url ? (
                <img
                  className="justice-photo-square"
                  src={api.justicePhotoUrl(j.id)}
                  alt={j.display_name}
                  loading={isFirst ? "eager" : "lazy"}
                />
              ) : (
                // A neutral placeholder in the frame's own color, not
                // an empty box -- a missing photo should never
                // collapse or distort the layout next to a Justice
                // who does have one.
                <div className="justice-photo-square justice-photo-placeholder-square" aria-hidden="true">
                  {(j.display_name || "?")[0]}
                </div>
              )}
            </div>
            <div className="justice-entry-info">
              {j.title && <p className={`justice-eyebrow justice-eyebrow-${accent}`}>{j.title}</p>}
              <h2 className="justice-name">{j.display_name}</h2>
              {isMe && (
                <p style={{ marginTop: "-0.25rem", marginBottom: "1rem" }}>
                  <Link to="/justices/me/edit" className="btn btn-secondary">
                    Edit my profile
                  </Link>
                </p>
              )}
              {j.why_care && (
                <p className={`justice-pull-quote justice-pull-quote-${accent}`}>&ldquo;{j.why_care}&rdquo;</p>
              )}
              {j.bio && <p className="justice-bio">{j.bio}</p>}
              {j.year_or_major && (
                <dl className="justice-facts">
                  <div>
                    <dt>Year / Major</dt>
                    <dd>{j.year_or_major}</dd>
                  </div>
                </dl>
              )}
              {interests.length > 0 && (
                <div className="justice-pills">
                  {interests.map((interest) => (
                    <span key={interest} className={`justice-pill justice-pill-${accent}`}>
                      {interest}
                    </span>
                  ))}
                </div>
              )}
              {!hasAnyContent && (
                <p style={{ color: "var(--ink-soft)" }}>This Justice has not filled out their profile yet.</p>
              )}
            </div>
          </section>
        );
      })}
    </article>
  );
}
