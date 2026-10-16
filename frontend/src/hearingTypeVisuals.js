// Court Passport redesign: the 5-category hearing-type color/icon system
// from the mockups, mapped onto the backend's real 8-value `tag_color` set
// (see hearing_types.py's TAG_COLORS). Only 3 of the 8 real groups have a
// clean match -- jury_trial, oral_argument, sentencing. The other 5 (trial,
// arraignment, scheduling, family_probate, other) fall back to a neutral
// "Other" treatment: this is load-bearing, not an edge case, since
// scheduling/arraignment/family_probate are common in real data.
//
// "Oral Argument" and "Motions Hearing" are merged into one visual category
// here (confirmed with the user): the backend has never distinguished them
// (same tag_color, and LearnTopic.applies_to_hearing_type_category is an
// even coarser enum) -- splitting them would mean new backend classification
// logic, which this redesign explicitly doesn't do.
//
// These hex values are hand-duplicated in styles.css's .tag-*/.tag-dot-*
// rules (no build-time JS->CSS token pipeline exists in this project) --
// a future color change must be made in both places, or they'll drift.
// See styles.css's matching comment near those rules.
export const HEARING_TYPE_VISUALS = {
  jury_trial: {
    solid: "var(--navy)", tint: "#E3E7EB", ink: "var(--navy)",
    label: "Jury Trial", icon: "two-people",
  },
  oral_argument: {
    solid: "var(--sage)", tint: "#E8ECDC", ink: "#465331",
    label: "Oral Argument", icon: "scales",
  },
  sentencing: {
    solid: "var(--plum)", tint: "#EDE7F0", ink: "var(--plum-deep)",
    label: "Sentencing", icon: "gavel",
  },
};

// trial (bench trial), arraignment, scheduling, family_probate, and other
// all fall back to this neutral treatment -- label comes from the hearing's
// own hearing_type_display text at the call site, not a bare "Other",
// since that's likely the majority of real hearings and shouldn't look vague.
export const OTHER_VISUAL = {
  solid: "var(--muted)", tint: "#E9EAEC", ink: "var(--muted)",
  icon: "document-neutral",
};

// Defined for spec completeness only -- no backend tag_color produces
// "closing_arguments" today (it's not one of the 8 real groups). Kept so
// the visual system is ready if a hearing-type rule for it is ever added.
// Note: a different, unrelated field (ProceedingStage.closing_arguments,
// Archive's "what did you see?" dropdown) already uses this same label for
// a different concept -- don't wire this into Archive without re-checking
// that collision risk.
export const CLOSING_ARGUMENTS_VISUAL = {
  solid: "var(--terracotta)", tint: "#F2E4DD", ink: "var(--terracotta-deep)",
  label: "Closing Arguments", icon: "speech-bubble",
};

export function getHearingTypeVisual(tagColor) {
  return HEARING_TYPE_VISUALS[tagColor] || OTHER_VISUAL;
}
