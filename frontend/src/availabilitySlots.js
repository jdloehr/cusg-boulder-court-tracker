// Phase-6.3 doc: client-side mirror of the slot-indexing/overlap additions
// in backend/app/availability.py -- the two can't literally share code
// across the Python/JS boundary, so they're kept deliberately small and
// each side is commented with a pointer to its counterpart. Any change to
// one should be checked against the other.
//
// Reuses parseHearingTimeMinutes/parseDurationMinutes/weekdayAbbr from
// availabilityMatch.js rather than duplicating them -- those functions
// didn't change in the Phase 6.3 redesign, only the block-vs-slot
// comparison logic did.
import { parseDurationMinutes, parseHearingTimeMinutes, weekdayAbbr } from "./availabilityMatch.js";

// Mirrors app.availability.SLOT_WINDOW_START_MIN/SLOT_MINUTES/NUM_SLOTS.
// 7:00 AM-8:00 PM in 30-min steps = 26 slots. See that module's comment
// for why 7am (not the doc's illustrative 8am default): 75 real
// production hearings start at exactly 7:00 AM.
export const SLOT_WINDOW_START_MIN = 7 * 60;
export const SLOT_MINUTES = 30;
export const NUM_SLOTS = 26;

export function slotStartMinutes(slotIndex) {
  return SLOT_WINDOW_START_MIN + slotIndex * SLOT_MINUTES;
}

export function slotEndMinutes(slotIndex) {
  return slotStartMinutes(slotIndex) + SLOT_MINUTES;
}

// Mirrors app.availability.hearing_overlapping_slots.
export function hearingOverlappingSlots(startMin, endMin) {
  const slots = new Set();
  for (let i = 0; i < NUM_SLOTS; i++) {
    if (slotStartMinutes(i) < endMin && startMin < slotEndMinutes(i)) slots.add(i);
  }
  return slots;
}

// Mirrors app.availability.hearing_matches_slots. `freeSlotsByDay` is a
// { [day_of_week]: Set<slot_index> } map, and `hearingDateISO` is a
// "YYYY-MM-DD" string, matching what GET /api/hearings returns for
// Hearing.date.
export function hearingMatchesSlots(hearingDateISO, hearingTime, hearingDuration, freeSlotsByDay) {
  const startMin = parseHearingTimeMinutes(hearingTime);
  if (startMin === null) return false;
  const endMin = startMin + parseDurationMinutes(hearingDuration);
  const day = weekdayAbbr(new Date(hearingDateISO + "T00:00:00"));
  const daySlots = freeSlotsByDay[day];
  if (!daySlots || daySlots.size === 0) return false;
  for (const slot of hearingOverlappingSlots(startMin, endMin)) {
    if (daySlots.has(slot)) return true;
  }
  return false;
}

// Converts a flat cells array ([{day_of_week, slot_index}, ...], the wire
// shape sent to/from the backend) into the {day: Set(slot_index)} shape
// hearingMatchesSlots expects.
export function cellsToFreeSlotsByDay(cells) {
  const byDay = {};
  for (const cell of cells || []) {
    if (!byDay[cell.day_of_week]) byDay[cell.day_of_week] = new Set();
    byDay[cell.day_of_week].add(cell.slot_index);
  }
  return byDay;
}
