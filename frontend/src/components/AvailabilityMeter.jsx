import { useState } from "react";

// Phase-6.2 doc, Section 4: a red-to-green bar (deliberately not a badge
// pill -- a different shape entirely from the recommendation star and the
// "fits your schedule" badge, so a Justice can tell all three apart at a
// glance). Renders only when the caller has already confirmed the viewer
// is a Justice (see HearingList.jsx) -- this component doesn't re-check
// that itself, since the data it's given (summary) only exists at all
// because that check already passed server-side.
//
// Rendered inline next to the hearing type, inside the row's own <Link>
// (see HearingList.jsx) -- a click here must not also navigate to the
// hearing's detail page, which is why the click handler stops the event
// before it can bubble up to that Link.
export default function AvailabilityMeter({ summary }) {
  const [expanded, setExpanded] = useState(false);
  if (!summary || summary.total === 0) return null;

  const ratio = summary.free_count / summary.total;
  // Red (0 free) to green (all free), interpolated through amber.
  const hue = Math.round(ratio * 120); // 0 = red, 120 = green
  const label = summary.time_known
    ? `${summary.free_count} of ${summary.total} Justices free`
    : `Time unknown -- can't compute availability`;

  function onClick(e) {
    e.preventDefault();
    e.stopPropagation();
    setExpanded((v) => !v);
  }

  return (
    <span className="availability-meter-wrap">
      <button
        type="button"
        onClick={onClick}
        title={label}
        className="availability-meter-bar"
        style={{ background: summary.time_known ? `hsl(${hue}, 70%, 45%)` : "var(--line)" }}
        aria-label={label}
      />
      {expanded && (
        <span className="availability-meter-reveal">
          {summary.time_known
            ? summary.free_justice_names.length > 0
              ? `Free: ${summary.free_justice_names.join(", ")}`
              : "No Justices free at this time"
            : "This hearing's time couldn't be parsed, so availability can't be computed."}
        </span>
      )}
    </span>
  );
}
