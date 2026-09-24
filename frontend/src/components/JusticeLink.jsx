import { Link } from "react-router-dom";

// Phase-3 doc, Section 4: a Justice's name should be a clickable link to
// their public profile everywhere it appears (the recommendation
// callout, attendance rows, an Archive entry's attendee list and
// byline) -- not just on the "Meet the Justices" page. One shared
// component + one CSS class (.justice-link, styles.css) so the visual
// treatment stays consistent everywhere, and visitors learn to recognize
// it as clickable throughout the site.
//
// Phase-6.2 doc, Section 1: individual /justices/:id pages are gone --
// every Justice's full profile now lives inline on one page
// (pages/Justices.jsx), so this links to that Justice's anchor there
// instead of a separate URL.
//
// Renders plain, unlinked text when justiceId is missing -- an Archive
// attendee name that didn't resolve to a current Justice (see
// AttendeeOut's docstring in app/schemas.py), or an old entry from
// before submitted_by_justice_id existed. Honest degradation, not an
// error.
export default function JusticeLink({ justiceId, children }) {
  if (!justiceId) return <>{children}</>;
  return (
    <Link to={`/justices#justice-${justiceId}`} className="justice-link">
      {children}
    </Link>
  );
}
