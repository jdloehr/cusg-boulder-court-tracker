import { Link } from "react-router-dom";

// Calendar-view doc, Feature 2: hearing-type tags become clickable
// everywhere they appear, linking to that specific hearing's detail page
// -- not a generic "all Jury Trials" filter. `color` is one of the 8
// tag_color groups from backend/app/hearing_types.py::TAG_COLORS
// (jury_trial/oral_argument/trial/sentencing/arraignment/scheduling/
// family_probate/other), matched here by a `.tag-{color}` CSS class.
//
// Renders plain, non-clickable text when hearingId isn't in scope yet
// (a static example, a loading skeleton) -- the doc's own explicit
// fallback, rather than a broken link.
export default function HearingTypeTag({ label, color, hearingId }) {
  const className = `hearing-tag tag-${color || "other"}`;

  if (!hearingId) {
    return <span className={className}>{label}</span>;
  }

  return (
    <Link
      to={`/hearings/${hearingId}`}
      className={className}
      // The tag's own destination (this specific hearing) must win over
      // whatever the surrounding card/row already links to or handles a
      // click for (the Archive card's photo, a Recommendations card
      // body, a month-calendar day cell's own "select this day" click).
      onClick={(e) => e.stopPropagation()}
    >
      {label}
    </Link>
  );
}
