"""
Phase-6.3 doc, Section 6: DB-backed helpers for reading/writing
AvailabilitySlot rows -- kept separate from app/availability.py (which
stays dependency-free pure functions, importable by app/models.py itself
for Hearing.time_sort_key) so these can import the ORM models without
creating a circular import.

Calendar-sync doc: also the home for AvailabilityOverride's read/write
helpers and the shared date-specific-wins-else-recurring resolver every
date-aware caller (the per-hearing meter, the month view's day-gauge)
goes through -- one choke point, not three copies of the same fallback
logic.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.availability import NUM_SLOTS, weekday_abbr
from app.models import AvailabilityOverride, AvailabilityOwnerType, AvailabilitySlot


def load_owner_cells(db: Session, owner_type: AvailabilityOwnerType, owner_id: str) -> list[dict]:
    """The raw {day_of_week, slot_index} cells for one owner (a Justice
    or a Subscription), for echoing back in an API response."""
    rows = (
        db.query(AvailabilitySlot)
        .filter(AvailabilitySlot.owner_type == owner_type, AvailabilitySlot.owner_id == owner_id)
        .all()
    )
    return [{"day_of_week": r.day_of_week.value, "slot_index": r.slot_index} for r in rows]


def load_free_slots_by_day(db: Session, owner_type: AvailabilityOwnerType, owner_id: str) -> dict[str, set[int]]:
    """The same rows, grouped into the {day_of_week: {slot_index, ...}}
    shape app.availability.hearing_matches_slots expects."""
    rows = (
        db.query(AvailabilitySlot)
        .filter(AvailabilitySlot.owner_type == owner_type, AvailabilitySlot.owner_id == owner_id)
        .all()
    )
    by_day: dict[str, set[int]] = {}
    for r in rows:
        by_day.setdefault(r.day_of_week.value, set()).add(r.slot_index)
    return by_day


def replace_owner_slots(db: Session, owner_type: AvailabilityOwnerType, owner_id: str, cells: list) -> None:
    """Full-replace semantics: delete every existing slot for this owner,
    then insert exactly the cells given. Does not commit -- the caller
    commits as part of its own transaction."""
    db.query(AvailabilitySlot).filter(
        AvailabilitySlot.owner_type == owner_type, AvailabilitySlot.owner_id == owner_id
    ).delete()
    db.add_all([
        AvailabilitySlot(owner_type=owner_type, owner_id=owner_id,
                          day_of_week=c.day_of_week, slot_index=c.slot_index)
        for c in cells
    ])


# --- Calendar-sync doc: date-specific overrides -----------------------------

def load_override_slots_by_date(
    db: Session, owner_type: AvailabilityOwnerType, owner_id: str,
    date_from: date | None = None, date_to: date | None = None,
) -> dict[date, set[int]]:
    """All override rows for one owner in an optional date range, grouped
    into {specific_date: {free slot_index, ...}}. A synced-but-fully-busy
    date still appears as an explicit empty set (not absent) -- that
    distinction is exactly what tells resolve_free_slots_for_date whether
    to trust this data or fall back to the recurring pattern, since
    app/jobs/google_calendar_sync.py always writes a full row per slot
    (is_free True or False) for every date it actually syncs, never just
    the free ones."""
    q = db.query(AvailabilityOverride).filter(
        AvailabilityOverride.owner_type == owner_type, AvailabilityOverride.owner_id == owner_id,
    )
    if date_from:
        q = q.filter(AvailabilityOverride.specific_date >= date_from)
    if date_to:
        q = q.filter(AvailabilityOverride.specific_date <= date_to)

    by_date: dict[date, set[int]] = {}
    synced_dates: set[date] = set()
    for r in q.all():
        synced_dates.add(r.specific_date)
        if r.is_free:
            by_date.setdefault(r.specific_date, set()).add(r.slot_index)
    for d in synced_dates:
        by_date.setdefault(d, set())
    return by_date


def resolve_free_slots_for_date(
    specific_date: date, override_slots_by_date: dict[date, set[int]], recurring_free_slots_by_day: dict[str, set[int]],
) -> set[int]:
    """Override rows for this exact date win if any exist (a synced
    Justice's real calendar for that day, even if it determined zero
    free slots); otherwise falls back to the recurring weekly pattern,
    completely unchanged for every manual-entry Justice, who never has
    override rows at all."""
    if specific_date in override_slots_by_date:
        return override_slots_by_date[specific_date]
    return recurring_free_slots_by_day.get(weekday_abbr(specific_date), set())


def replace_owner_overrides_for_window(
    db: Session, owner_type: AvailabilityOwnerType, owner_id: str,
    date_from: date, date_to: date, free_slots_by_date: dict[date, set[int]],
) -> None:
    """Full-replace semantics scoped to [date_from, date_to]: deletes
    every existing override row for this owner in that window, then
    writes a full row for *every* slot of *every* date in
    free_slots_by_date (is_free True or False), not just the free ones --
    so "determined busy" and "never synced" stay unambiguous to
    load_override_slots_by_date above. Does not commit -- the caller
    commits as part of its own transaction, same convention as
    replace_owner_slots."""
    db.query(AvailabilityOverride).filter(
        AvailabilityOverride.owner_type == owner_type, AvailabilityOverride.owner_id == owner_id,
        AvailabilityOverride.specific_date >= date_from, AvailabilityOverride.specific_date <= date_to,
    ).delete()
    for d, free_slots in free_slots_by_date.items():
        db.add_all([
            AvailabilityOverride(owner_type=owner_type, owner_id=owner_id, specific_date=d,
                                  slot_index=i, is_free=i in free_slots)
            for i in range(NUM_SLOTS)
        ])


def delete_all_owner_overrides(db: Session, owner_type: AvailabilityOwnerType, owner_id: str) -> None:
    """Every override row for this owner, with no date bound -- used on
    disconnect (routers/google_calendar.py), where there's no "current
    sync window" left to scope a delete to once the connection itself is
    gone. Does not commit."""
    db.query(AvailabilityOverride).filter(
        AvailabilityOverride.owner_type == owner_type, AvailabilityOverride.owner_id == owner_id,
    ).delete()
