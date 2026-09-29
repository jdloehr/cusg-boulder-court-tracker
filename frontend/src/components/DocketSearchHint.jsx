import { parseCaseNumberParts } from "../caseNumber.js";

// Real bug, found live: the official docket search page
// (coloradojudicial.gov/dockets) has no single "case number" field --
// its Case Number fieldset splits into three separate inputs (4-Digit
// Year, a Case Class dropdown, and a numeric-only Case Sequence field),
// and the search form itself submits via POST, so a `?caseNumber=...`
// query-string link (what this used to be) can never pre-fill or
// trigger a search on it -- it silently always lands on the blank form.
// There's no reliable way to deep-link into a third-party POST form we
// don't control, so this shows the three parts to copy in by hand
// instead of pretending a link can do it for you.
export default function DocketSearchHint({ caseNumber, className = "btn btn-secondary" }) {
  const parts = parseCaseNumberParts(caseNumber);
  return (
    <span style={{ display: "inline-block" }}>
      <a className={className} href="https://www.coloradojudicial.gov/dockets" target="_blank" rel="noreferrer">
        Search official docket
      </a>
      {parts && (
        <span style={{ display: "block", fontSize: "0.78rem", color: "var(--ink-soft)", marginTop: "0.3rem" }}>
          Their search has 3 separate fields, not one box -- enter Year <strong>{parts.year}</strong>, Case Class{" "}
          <strong>{parts.caseClass}</strong>, Sequence <strong>{parts.sequence}</strong> (not the combined "{caseNumber}").
        </span>
      )}
    </span>
  );
}
