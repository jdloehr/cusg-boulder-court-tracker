import { Fragment, useRef, useState } from "react";
import { NUM_SLOTS, SLOT_MINUTES, SLOT_WINDOW_START_MIN } from "../availabilitySlots.js";

// Phase-6.3 doc: the When2Meet-style click-and-drag grid, replacing the
// old form-based day+start-time+end-time row editor (AvailabilityBlockEditor,
// removed). Shared by a Justice's own recurring availability
// (EditJusticeProfile.jsx, writes to the server) and a visitor's personal
// availability (AvailabilityPanel.jsx / Subscribe.jsx, writes to
// localStorage) -- shared UI only, two completely separate data paths.
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_LABELS = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

function slotLabel(slotIndex) {
  const totalMin = SLOT_WINDOW_START_MIN + slotIndex * SLOT_MINUTES;
  const hour24 = Math.floor(totalMin / 60);
  const min = totalMin % 60;
  const ampm = hour24 >= 12 ? "PM" : "AM";
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return `${hour12}:${String(min).padStart(2, "0")} ${ampm}`;
}

function cellKey(day, slotIndex) {
  return `${day}:${slotIndex}`;
}

function cellsToSet(cells) {
  return new Set((cells || []).map((c) => cellKey(c.day_of_week, c.slot_index)));
}

function setToCells(set) {
  return [...set].map((key) => {
    const [day, slotIndexStr] = key.split(":");
    return { day_of_week: day, slot_index: Number(slotIndexStr) };
  });
}

// `cells`: array of {day_of_week, slot_index} -- the exact wire shape
// sent to/from the backend (and, for the visitor path, localStorage).
// Parent owns the committed state; onChange fires once per completed
// interaction (a single click, or a whole drag), not once per cell.
export default function AvailabilityGrid({ cells, onChange }) {
  const committed = cellsToSet(cells);
  const [liveSelected, setLiveSelected] = useState(null); // non-null only while actively dragging
  const dragModeRef = useRef(null); // "paint" | "clear"
  const draggingSetRef = useRef(null);

  const displayed = liveSelected ?? committed;

  function applyCell(set, day, slotIndex, mode) {
    const key = cellKey(day, slotIndex);
    if (mode === "paint") set.add(key);
    else set.delete(key);
  }

  function handlePointerDown(e, day, slotIndex) {
    e.preventDefault();
    const key = cellKey(day, slotIndex);
    const mode = committed.has(key) ? "clear" : "paint";
    dragModeRef.current = mode;
    const working = new Set(committed);
    applyCell(working, day, slotIndex, mode);
    draggingSetRef.current = working;
    setLiveSelected(new Set(working));
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }

  function handlePointerMove(e) {
    if (!dragModeRef.current || !draggingSetRef.current) return;
    // Painting across sibling cells under one pointer/finger needs to look
    // up whatever element is currently underneath it -- pointer capture
    // keeps events firing on the cell the drag started on, not the one
    // the finger/cursor is actually over.
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const cellEl = el?.closest?.("[data-day]");
    if (!cellEl) return;
    applyCell(draggingSetRef.current, cellEl.dataset.day, Number(cellEl.dataset.slot), dragModeRef.current);
    setLiveSelected(new Set(draggingSetRef.current));
  }

  function endDrag() {
    if (draggingSetRef.current) {
      onChange(setToCells(draggingSetRef.current));
    }
    dragModeRef.current = null;
    draggingSetRef.current = null;
    setLiveSelected(null);
  }

  return (
    <div className="availability-grid-wrap">
      <div
        className="availability-grid"
        style={{ gridTemplateColumns: `4rem repeat(${DAYS.length}, 1fr)` }}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div className="availability-grid-corner" />
        {DAYS.map((day) => (
          <div key={day} className="availability-grid-day-label">
            {DAY_LABELS[day]}
          </div>
        ))}
        {Array.from({ length: NUM_SLOTS }, (_, slotIndex) => (
          <Fragment key={slotIndex}>
            <div className="availability-grid-time-label">
              {slotIndex % 2 === 0 ? slotLabel(slotIndex) : ""}
            </div>
            {DAYS.map((day) => {
              const isSelected = displayed.has(cellKey(day, slotIndex));
              return (
                <button
                  key={day}
                  type="button"
                  data-day={day}
                  data-slot={slotIndex}
                  className={`availability-grid-cell${isSelected ? " is-selected" : ""}`}
                  onPointerDown={(e) => handlePointerDown(e, day, slotIndex)}
                  aria-label={`${DAY_LABELS[day]} ${slotLabel(slotIndex)}`}
                  aria-pressed={isSelected}
                />
              );
            })}
          </Fragment>
        ))}
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => onChange([])} style={{ marginTop: "0.75rem" }}>
        Clear all
      </button>
    </div>
  );
}
