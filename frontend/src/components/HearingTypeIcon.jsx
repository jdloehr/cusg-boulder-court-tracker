// Page-redesign doc, Page 4 (Learn sidebar): "a small inline SVG icon"
// per hearing type. Hand-authored, same convention as ColonnadeMotif.jsx
// -- this project has no icon library/asset pipeline. Only the two real
// HearingTypeCategory values a LearnTopic can target get an icon; there's
// nothing else to draw one for (see app/models.py::HearingTypeCategory).
//
// Court Passport redesign: icon shapes match hearingTypeVisuals.js's
// assignment (two-people for jury_trial, scales for oral_argument) --
// this component's own input is HearingTypeCategory's 2 values
// (jury_trial/oral_argument_motions), a different, coarser enum than
// hearingTypeVisuals.js's 8-value tag_color set, so oral_argument_motions
// is mapped locally to that file's "oral_argument" entry rather than
// broadening this component's input contract.
export default function HearingTypeIcon({ type, ...props }) {
  const common = { width: "1rem", height: "1rem", viewBox: "0 0 24 24", "aria-hidden": "true", ...props };
  if (type === "jury_trial") {
    // Two people -- jury trial.
    return (
      <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="9" cy="8" r="3" />
        <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
        <circle cx="17" cy="9" r="2.5" />
        <path d="M16 14.2c2.9.3 5 2.7 5 5.8" />
      </svg>
    );
  }
  // Scales -- oral argument / motions (oral_argument_motions).
  return (
    <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v18" />
      <path d="M5 7l-3 6a4 4 0 0 0 6 0z" />
      <path d="M19 7l-3 6a4 4 0 0 0 6 0z" />
      <path d="M5 7h14" />
    </svg>
  );
}
