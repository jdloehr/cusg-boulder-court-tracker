// Page-redesign doc, Page 4 (Learn sidebar): "a small inline SVG icon"
// per hearing type. Hand-authored, same convention as ColonnadeMotif.jsx
// -- this project has no icon library/asset pipeline. Only the two real
// HearingTypeCategory values a LearnTopic can target get an icon; there's
// nothing else to draw one for (see app/models.py::HearingTypeCategory).
export default function HearingTypeIcon({ type, ...props }) {
  const common = { width: "1rem", height: "1rem", viewBox: "0 0 24 24", "aria-hidden": "true", ...props };
  if (type === "jury_trial") {
    // A simple gavel glyph.
    return (
      <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.6">
        <rect x="3" y="13" width="8" height="3" rx="0.5" transform="rotate(-45 7 14.5)" />
        <line x1="9.5" y1="11" x2="15.5" y2="17" strokeLinecap="round" />
        <line x1="4" y1="20" x2="12" y2="20" strokeLinecap="round" />
        <line x1="17" y1="9" x2="21" y2="13" strokeLinecap="round" />
      </svg>
    );
  }
  // Oral argument / motions -- a simple speech-bubble glyph.
  return (
    <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 5h16v10H9l-4 4v-4H4z" strokeLinejoin="round" />
    </svg>
  );
}
