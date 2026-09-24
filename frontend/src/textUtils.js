// Shared by HearingList.jsx and Home.jsx (Phase-6.2 doc, Section 3): both
// need to shorten a hearing's often-essay-length `hearing_type_display`
// ("Jury Trial: a full trial where...") down to just its short label for
// a docket-style row/badge, leaving the fuller explanation for the
// hearing's own detail page.
export function firstSentence(text) {
  if (!text) return "";
  const idx = text.indexOf(": ");
  return idx > -1 ? text.slice(0, idx) : text.split(". ")[0];
}
