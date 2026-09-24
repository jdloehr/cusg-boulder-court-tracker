// Phase-6.2/6.3 docs: client-side mirror of backend/app/availability.py's
// time-parsing functions, used for the public, browser-local "fits your
// schedule" matching -- the two implementations can't literally share code
// across the Python/JS boundary, so they're kept deliberately small and
// each side is commented with a pointer to its counterpart. Any change to
// one should be checked against the other.
//
// Phase 6.3 moved the actual slot-overlap matching (the old
// hearingMatchesBlocks/blockOverlaps pair, since removed) into
// availabilitySlots.js, since availability is now a painted grid of
// slots rather than typed time ranges -- this file keeps only the parsing
// functions that didn't change.

export const WEEKDAY_ABBRS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

// Mirrors app.availability.DEFAULT_HEARING_DURATION_MINUTES.
export const DEFAULT_HEARING_DURATION_MINUTES = 60;

const DURATION_RE = /(\d+)\s*(day|hour|hr|minute|min)s?/gi;
const UNIT_MINUTES = { day: 24 * 60, hour: 60, hr: 60, minute: 1, min: 1 };

// Mirrors app.availability.parse_hearing_time.
export function parseHearingTimeMinutes(raw) {
  const text = (raw || "").trim().toUpperCase();
  if (!text) return null;
  const match = text.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)?$/);
  if (!match) return null;
  let hour = parseInt(match[1], 10);
  const minute = parseInt(match[2], 10);
  const ampm = match[3];
  if (ampm === "PM" && hour !== 12) hour += 12;
  if (ampm === "AM" && hour === 12) hour = 0;
  if (hour > 23 || minute > 59) return null;
  return hour * 60 + minute;
}

// Mirrors app.availability.parse_duration_minutes.
export function parseDurationMinutes(raw) {
  if (!raw) return DEFAULT_HEARING_DURATION_MINUTES;
  let total = 0;
  let match;
  DURATION_RE.lastIndex = 0;
  while ((match = DURATION_RE.exec(raw)) !== null) {
    total += parseInt(match[1], 10) * UNIT_MINUTES[match[2].toLowerCase()];
  }
  return total > 0 ? total : DEFAULT_HEARING_DURATION_MINUTES;
}

// Mirrors app.availability.weekday_abbr -- note JS's Date.getDay() (Sun=0)
// numbers differently than Python's date.weekday() (Mon=0), which is
// exactly why day_of_week is stored as a string, not an integer.
export function weekdayAbbr(dateObj) {
  const jsSundayFirst = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  return jsSundayFirst[dateObj.getDay()];
}

