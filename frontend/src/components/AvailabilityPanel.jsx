import { useState } from "react";
import { Link } from "react-router-dom";
import AvailabilityBlockEditor from "./AvailabilityBlockEditor.jsx";
import { useVisitorAvailability } from "../useVisitorAvailability.js";

// Phase-6.2 doc, Section 5: a personal version of the availability idea
// for any visitor, no login -- entirely browser-local unless they
// explicitly subscribe (Section 6, via the "Get this as a weekly email"
// link below). A completely separate, unconnected data path from the
// Justice-only availability in Section 4: never sent to the server here,
// never merged with Justice data.
export default function AvailabilityPanel() {
  const { blocks, setBlocks, enabled, setEnabled } = useVisitorAvailability();
  const [open, setOpen] = useState(false);

  return (
    <div className="card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{ background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left", width: "100%" }}
      >
        <h3 style={{ margin: 0 }}>{open ? "▾" : "▸"} My availability</h3>
      </button>
      {!open && (
        <p className="disclaimer" style={{ margin: "0.4rem 0 0" }}>
          Enter your free time to see which hearings fit your schedule -- stays in your browser only.
        </p>
      )}
      {open && (
        <div style={{ marginTop: "0.75rem" }}>
          <p className="disclaimer" style={{ marginTop: 0 }}>
            Stored only in this browser -- never sent anywhere unless you subscribe to a matching email
            below.
          </p>
          <AvailabilityBlockEditor blocks={blocks} onChange={setBlocks} />
          <label className="filter-checkbox" style={{ marginTop: "0.75rem" }}>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              disabled={blocks.length === 0}
            />
            Show hearings that fit my schedule
          </label>
          {blocks.length > 0 && (
            <p style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>
              Want this as a weekly email instead?{" "}
              <Link to="/subscribe?filterType=personal_availability">Get the weekly digest</Link>.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
