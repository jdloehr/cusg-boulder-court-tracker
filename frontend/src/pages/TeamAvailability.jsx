import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import { NUM_SLOTS, SLOT_MINUTES, SLOT_WINDOW_START_MIN } from "../availabilitySlots.js";

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

// Phase-6.3 doc, Section 4: "each cell shaded red-to-green based on how
// many Justices are free" -- muted terracotta-to-sage rather than
// saturated stoplight colors, matching the same hue-sweep technique
// AvailabilityMeter.jsx already uses, tuned toward desaturated/lighter.
function cellColor(freeCount, total) {
  if (total === 0) return "var(--line)";
  const ratio = freeCount / total;
  const hue = 10 + ratio * 135; // 10 = terracotta, 145 = sage
  return `hsl(${hue}, 30%, 62%)`;
}

// Phase-6.3 doc, Section 4: self-gated the same way EditJusticeProfile.jsx
// is -- a dedicated route, not a tab inside the curation-focused admin
// dashboard, since this is Justice-identity data, not curation-role data.
export default function TeamAvailability() {
  const admin = getStoredAdmin();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [expandedKey, setExpandedKey] = useState(null);

  useEffect(() => {
    api.teamAvailability().then(setData).catch((e) => setError(e.message));
  }, []);

  if (!admin?.isJustice) return <Navigate to="/admin/login" replace />;
  if (error) return <p className="message-error">{error}</p>;
  if (!data) return <p>Loading&hellip;</p>;

  const cellsByKey = {};
  for (const c of data.cells) cellsByKey[`${c.day_of_week}:${c.slot_index}`] = c;

  return (
    <article>
      <h1>Team Availability</h1>
      <p className="disclaimer">
        Justices only -- never shown publicly. Every cell is shaded by how many of the court's{" "}
        {data.total_justices} Justices are free then; click a cell to see exactly who.
      </p>

      <div className="availability-grid-wrap">
        <div
          className="availability-grid"
          style={{ gridTemplateColumns: `4rem repeat(${DAYS.length}, 1fr)` }}
        >
          <div className="availability-grid-corner" />
          {DAYS.map((day) => (
            <div key={day} className="availability-grid-day-label">
              {DAY_LABELS[day]}
            </div>
          ))}
          {Array.from({ length: NUM_SLOTS }, (_, slotIndex) => (
            <span key={slotIndex} style={{ display: "contents" }}>
              <div className="availability-grid-time-label">
                {slotIndex % 2 === 0 ? slotLabel(slotIndex) : ""}
              </div>
              {DAYS.map((day) => {
                const key = `${day}:${slotIndex}`;
                const cell = cellsByKey[key];
                return (
                  <button
                    key={day}
                    type="button"
                    className="team-availability-cell"
                    style={{ background: cellColor(cell?.free_count ?? 0, data.total_justices) }}
                    onClick={() => setExpandedKey(expandedKey === key ? null : key)}
                    aria-label={`${DAY_LABELS[day]} ${slotLabel(slotIndex)}: ${cell?.free_count ?? 0} of ${data.total_justices} free`}
                  />
                );
              })}
            </span>
          ))}
        </div>
      </div>

      {expandedKey && (
        <div className="card" style={{ marginTop: "1rem" }}>
          {(() => {
            const cell = cellsByKey[expandedKey];
            const [day, slotIndexStr] = expandedKey.split(":");
            return (
              <>
                <h3 style={{ marginTop: 0 }}>
                  {DAY_LABELS[day]} {slotLabel(Number(slotIndexStr))}
                </h3>
                <p style={{ margin: 0 }}>
                  {cell.free_count} of {cell.total} free
                  {cell.free_justice_names.length > 0 ? `: ${cell.free_justice_names.join(", ")}` : ""}
                </p>
              </>
            );
          })()}
        </div>
      )}
    </article>
  );
}
