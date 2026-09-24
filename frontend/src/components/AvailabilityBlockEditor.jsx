import { WEEKDAY_ABBRS } from "../availabilityMatch.js";

const DAY_LABELS = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

// Phase-6.2 doc, Section 4/5: the same repeatable day + time-range row
// interaction used both by a Justice's own recurring availability
// (EditJusticeProfile.jsx, writes to the server) and a visitor's personal
// availability (AvailabilityPanel.jsx / Subscribe.jsx, writes to
// localStorage) -- shared UI only, two completely separate data paths.
export default function AvailabilityBlockEditor({ blocks, onChange }) {
  function updateBlock(index, field, value) {
    const next = blocks.map((b, i) => (i === index ? { ...b, [field]: value } : b));
    onChange(next);
  }

  function addBlock() {
    onChange([...blocks, { day_of_week: "mon", start_time: "09:00", end_time: "17:00" }]);
  }

  function removeBlock(index) {
    onChange(blocks.filter((_, i) => i !== index));
  }

  return (
    <div>
      {blocks.map((block, index) => (
        <div key={index} style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.5rem" }}>
          <select
            aria-label="Day of week"
            value={block.day_of_week}
            onChange={(e) => updateBlock(index, "day_of_week", e.target.value)}
          >
            {WEEKDAY_ABBRS.map((d) => (
              <option key={d} value={d}>
                {DAY_LABELS[d]}
              </option>
            ))}
          </select>
          <input
            aria-label="Start time"
            type="time"
            value={block.start_time}
            onChange={(e) => updateBlock(index, "start_time", e.target.value)}
          />
          <span>to</span>
          <input
            aria-label="End time"
            type="time"
            value={block.end_time}
            onChange={(e) => updateBlock(index, "end_time", e.target.value)}
          />
          <button type="button" className="btn btn-secondary" onClick={() => removeBlock(index)}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="btn btn-secondary" onClick={addBlock}>
        Add a time block
      </button>
    </div>
  );
}
