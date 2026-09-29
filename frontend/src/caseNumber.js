// Mirrors the year/type/seq split in backend/app/case_categories.py's
// CASE_NUMBER_RE -- used here purely for display (helping a human fill
// out the official docket search's three separate fields), not for
// case-category decoding, which stays a backend-only concern.
const CASE_NUMBER_RE = /^(\d{2}|\d{4})([A-Za-z]+)(\d+)$/;

export function parseCaseNumberParts(caseNumber) {
  const match = CASE_NUMBER_RE.exec((caseNumber || "").trim());
  if (!match) return null;
  const [, year, caseClass, sequence] = match;
  return {
    year: year.length === 2 ? `20${year}` : year,
    caseClass: caseClass.toUpperCase(),
    sequence,
  };
}
