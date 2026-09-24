"""
Phase-6.3 doc, Section 6: DB-backed helpers for reading/writing
AvailabilitySlot rows -- kept separate from app/availability.py (which
stays dependency-free pure functions, importable by app/models.py itself
for Hearing.time_sort_key) so these can import the ORM models without
creating a circular import.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AvailabilityOwnerType, AvailabilitySlot


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
