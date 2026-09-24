"""
Phase-6.2/6.3 docs: shared time-parsing logic used by the Justice-only
availability meter, the digest job's `personal_availability` subscription
matching, and mirrored in JS by frontend/src/availabilityMatch.js /
availabilitySlots.js for the public, client-side matching (see those
files' own header comments -- the two can't literally share code across
the language boundary, so they're kept deliberately small and commented
as a pair).

Phase-6.3 doc replaced the original range-block representation
({day_of_week, start_time, end_time}) with a fixed weekly grid of 30-min
slots (see SLOT_WINDOW_START_MIN/SLOT_MINUTES/NUM_SLOTS below), painted
cell-by-cell rather than typed as a time range -- the actual slot data
now lives in the AvailabilitySlot table (app/models.py) and is loaded
into a `{day_of_week: {slot_index, ...}}` dict by
app/availability_slots.py before being passed to hearing_matches_slots.
`day_of_week` stays a lowercase 3-letter abbreviation, not an integer --
Python's date.weekday() (Mon=0) and JS's Date.getDay() (Sun=0) disagree
on numbering, and a string sidesteps that mismatch entirely.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

WEEKDAY_ABBRS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Hearing.duration is free-text from the docket source with no
# established format (confirmed: no existing parser for it anywhere in
# this codebase) -- when it can't be parsed, this fixed, documented
# fallback is used instead of pretending a real duration is known.
DEFAULT_HEARING_DURATION_MINUTES = 60

_DURATION_RE = re.compile(r"(\d+)\s*(day|hour|hr|minute|min)s?", re.IGNORECASE)
_UNIT_MINUTES = {"day": 24 * 60, "hour": 60, "hr": 60, "minute": 1, "min": 1}


def parse_hearing_time(raw: Optional[str]) -> Optional[int]:
    """Minutes since midnight, or None if unparseable/blank. Factored out
    of Hearing.time_sort_key so this exact parsing logic has exactly one
    home instead of being duplicated for the availability meter and the
    digest matcher too. Mirrored in JS by
    frontend/src/availabilityMatch.js::parseHearingTimeMinutes -- keep
    both in sync if this changes."""
    text = (raw or "").strip().upper()
    if not text:
        return None
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def parse_duration_minutes(raw: Optional[str]) -> int:
    """Best-effort: sum every "<N> <unit>" pair found in the free text
    (handles "2 hours", "45 minutes", "1 hour 30 minutes", "1 day", ...).
    Falls back to DEFAULT_HEARING_DURATION_MINUTES if nothing matches."""
    if not raw:
        return DEFAULT_HEARING_DURATION_MINUTES
    total = 0
    for amount, unit in _DURATION_RE.findall(raw):
        total += int(amount) * _UNIT_MINUTES[unit.lower()]
    return total if total > 0 else DEFAULT_HEARING_DURATION_MINUTES


def weekday_abbr(d: date) -> str:
    return WEEKDAY_ABBRS[d.weekday()]


# --- Phase-6.3 doc: the fixed weekly grid ------------------------------
# 7:00 AM-8:00 PM in 30-min steps = 26 slots. Chosen over the doc's
# illustrative 8:00 AM-8:00 PM default after checking real production
# data: 75 real upcoming hearings start at exactly 7:00 AM, which an
# 8:00 AM floor would have made permanently, structurally unmatchable
# for every Justice and visitor. A handful of real outliers (a few
# "1:00/1:30 AM" docket-parsing-noise entries, one real 8:15 PM hearing)
# fall outside this window and can never match anyone's painted
# availability -- an accepted trade-off of any bounded grid, see
# test_hearing_outside_grid_window_never_matches.
SLOT_WINDOW_START_MIN = 7 * 60  # 7:00 AM
SLOT_MINUTES = 30
NUM_SLOTS = 26  # 7:00 AM - 8:00 PM


def slot_start_minutes(slot_index: int) -> int:
    return SLOT_WINDOW_START_MIN + slot_index * SLOT_MINUTES


def slot_end_minutes(slot_index: int) -> int:
    return slot_start_minutes(slot_index) + SLOT_MINUTES


def hearing_overlapping_slots(start_min: int, end_min: int) -> set[int]:
    """Which of the fixed grid slots this [start, end) interval touches.
    A hearing wholly outside the 7am-8pm window returns an empty set --
    it can never match any painted-free cell."""
    return {
        i for i in range(NUM_SLOTS)
        if slot_start_minutes(i) < end_min and start_min < slot_end_minutes(i)
    }


def hearing_matches_slots(
    hearing_date: date,
    hearing_time: Optional[str],
    hearing_duration: Optional[str],
    free_slots_by_day: dict[str, set[int]],
) -> bool:
    """True if the hearing's [start, start+duration) interval overlaps
    any slot marked free on the matching day-of-week. A hearing with an
    unparseable/blank time never matches (never a false positive).
    Mirrored in JS by frontend/src/availabilitySlots.js::hearingMatchesSlots."""
    start_min = parse_hearing_time(hearing_time)
    if start_min is None:
        return False
    end_min = start_min + parse_duration_minutes(hearing_duration)
    day_slots = free_slots_by_day.get(weekday_abbr(hearing_date), set())
    if not day_slots:
        return False
    return bool(hearing_overlapping_slots(start_min, end_min) & day_slots)
