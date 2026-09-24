"""
Phase-6.2 doc, Section 4/5/6: shared time-parsing and day/time-range
overlap logic used by the Justice-only availability meter (Section 4),
the digest job's `personal_availability` subscription matching (Section
6), and mirrored in JS by frontend/src/availabilityMatch.js for the
public, client-side matching in Section 5 (see that file's own header
comment -- the two can't literally share code across the language
boundary, so they're kept deliberately small and commented as a pair).

Availability blocks are always the same shape, stored as JSON text
(matching this codebase's existing convention -- no native JSON column
type is used anywhere in this project):
    [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}, ...]
`day_of_week` is a lowercase 3-letter abbreviation, not an integer --
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


def _block_overlaps(start_min: int, end_min: int, block: dict) -> bool:
    block_start = parse_hearing_time(block.get("start_time"))
    block_end = parse_hearing_time(block.get("end_time"))
    if block_start is None or block_end is None:
        return False
    # Standard half-open interval overlap: block_start < hearing_end and
    # hearing_start < block_end.
    return block_start < end_min and start_min < block_end


def hearing_matches_blocks(
    hearing_date: date,
    hearing_time: Optional[str],
    hearing_duration: Optional[str],
    blocks: list[dict],
) -> bool:
    """True if the hearing's [start, start+duration) interval overlaps
    any block on the matching day-of-week. A hearing with an
    unparseable/blank time never matches (never a false positive)."""
    start_min = parse_hearing_time(hearing_time)
    if start_min is None:
        return False
    end_min = start_min + parse_duration_minutes(hearing_duration)
    day = weekday_abbr(hearing_date)
    return any(
        block.get("day_of_week") == day and _block_overlaps(start_min, end_min, block)
        for block in blocks
    )
