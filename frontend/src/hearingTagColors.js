// Client-side mirror of backend/app/hearing_types.py::TAG_COLORS -- same
// convention already used for CASE_CATEGORY_LABELS/HEARING_TYPE_LABELS
// elsewhere (courtInfo.js, Learn.jsx): the backend is the source of truth
// for which bucket a given hearing actually falls into (already returned
// as `tag_color`/`hearing_tag_color` on every hearing/recommendation/
// archive-entry API response); this is just the display label for each
// bucket, for the month calendar's legend.
export const TAG_COLOR_LEGEND = [
  { key: "jury_trial", label: "Jury Trial" },
  { key: "oral_argument", label: "Oral Argument / Motions" },
  { key: "trial", label: "Bench/Court Trial" },
  { key: "sentencing", label: "Sentencing" },
  { key: "arraignment", label: "Arraignment / Advisement" },
  { key: "scheduling", label: "Scheduling / Procedural" },
  { key: "family_probate", label: "Family / Probate" },
  { key: "other", label: "Other" },
];

// Court Passport redesign: the month calendar's *visible* swatch legend
// collapses to the 4 colors the redesign actually uses (trial/arraignment/
// scheduling/family_probate/other all share one neutral dot color -- see
// hearingTypeVisuals.js) -- a display simplification only. TAG_COLOR_LEGEND
// above stays full-fidelity for anywhere that still needs a distinct label
// per real tag_color (e.g. the day sidebar's per-type hearing counts).
export const SIMPLIFIED_TAG_COLOR_LEGEND = [
  { key: "jury_trial", label: "Jury Trial" },
  { key: "oral_argument", label: "Oral Argument" },
  { key: "sentencing", label: "Sentencing" },
  { key: "other", label: "Other" },
];
