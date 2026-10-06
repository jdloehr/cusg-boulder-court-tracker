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

// Oct 2026 review, Phase 4 item 5: one shared date/time format
// ("Mon, Oct 5 · 8:30 AM", "Today"/"Tomorrow" where they apply)
// instead of each page picking its own mix of a raw ISO string
// ("2026-10-05") and ad hoc toLocaleDateString()/toLocaleString()
// calls -- used on Home, Recommendations, Archive, the Calendar (list
// and month views), and hearing detail.
export function formatHearingDate(dateISO) {
  if (!dateISO) return "";
  const date = new Date(`${dateISO}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.round((date - today) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Tomorrow";
  return date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export function formatHearingDateTime(dateISO, time) {
  return `${formatHearingDate(dateISO)} · ${time || "Time TBD"}`;
}

// Colorado's own real case-naming convention: a single-defendant
// criminal/misdemeanor/traffic docket entry is styled "People v.
// {defendant}" in official usage, even though "People" (the
// prosecuting party) never actually appears in the docket export's
// free-text Name field this app parses -- see
// app/jobs/docket_pull.py::re_split_parties, which only ever sees
// what's actually in that column. Any other single-party case (e.g. a
// probate "In re" filing) is shown bare, with no fabricated "v."
// this app has no basis for. Two or more parsed parties are already a
// real "A v. B" pair (or occasionally more) and are joined as-is.
const PROSECUTORIAL_CATEGORIES = new Set(["criminal", "misdemeanor", "traffic"]);

export function caseName(hearing) {
  const parties = (hearing.party_names || []).filter(Boolean);
  if (parties.length >= 2) return parties.join(" v. ");
  if (parties.length === 1) {
    return PROSECUTORIAL_CATEGORIES.has(hearing.case_category) ? `People v. ${parties[0]}` : parties[0];
  }
  return null;
}
