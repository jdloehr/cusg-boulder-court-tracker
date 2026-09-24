import { useCallback, useEffect, useState } from "react";
import { hearingOverlappingSlots } from "./availabilitySlots.js";
import { parseHearingTimeMinutes } from "./availabilityMatch.js";

// Phase-6.2/6.3 docs: a visitor's personal availability, stored
// browser-local only unless they explicitly subscribe (Section 6) --
// no server-side record of it exists by default. Follows this codebase's
// existing flat, `cusg_`-prefixed localStorage convention (see api.js),
// wrapped in try/catch for private-browsing tolerance.
const OLD_BLOCKS_KEY = "cusg_visitor_availability"; // Phase-6.2 shape: range blocks
const CELLS_KEY = "cusg_visitor_availability_cells"; // Phase-6.3 shape: painted grid cells
const ENABLED_KEY = "cusg_visitor_availability_enabled";

// Phase-6.3 doc, Section 5: a one-time, best-effort conversion of
// anything already saved under the old range-block shape, so a visitor
// who painted availability before this redesign doesn't silently lose
// it. Each old {day_of_week, start_time, end_time} block becomes
// whichever grid cells it overlaps -- any portion of an old block
// outside the fixed 7am-8pm grid window is silently dropped, since the
// grid can't represent it either way. Naturally idempotent: once the new
// key exists, this is never called again.
function migrateOldBlocksToCells() {
  try {
    const rawOld = localStorage.getItem(OLD_BLOCKS_KEY);
    if (!rawOld) return [];
    const oldBlocks = JSON.parse(rawOld);
    const cells = [];
    for (const block of oldBlocks) {
      const startMin = parseHearingTimeMinutes(block.start_time);
      const endMin = parseHearingTimeMinutes(block.end_time);
      if (startMin === null || endMin === null) continue;
      for (const slotIndex of hearingOverlappingSlots(startMin, endMin)) {
        cells.push({ day_of_week: block.day_of_week, slot_index: slotIndex });
      }
    }
    return cells;
  } catch {
    return [];
  }
}

function readCells() {
  try {
    const raw = localStorage.getItem(CELLS_KEY);
    if (raw) return JSON.parse(raw);
    const migrated = migrateOldBlocksToCells();
    if (migrated.length > 0) {
      localStorage.setItem(CELLS_KEY, JSON.stringify(migrated));
    }
    return migrated;
  } catch {
    return [];
  }
}

function readEnabled() {
  try {
    return localStorage.getItem(ENABLED_KEY) === "true";
  } catch {
    return false;
  }
}

export function useVisitorAvailability() {
  const [cells, setCellsState] = useState(readCells);
  const [enabled, setEnabledState] = useState(readEnabled);

  useEffect(() => {
    try {
      localStorage.setItem(CELLS_KEY, JSON.stringify(cells));
    } catch {
      /* localStorage unavailable (e.g. private browsing) -- just don't persist */
    }
  }, [cells]);

  useEffect(() => {
    try {
      localStorage.setItem(ENABLED_KEY, enabled ? "true" : "false");
    } catch {
      /* ignore */
    }
  }, [enabled]);

  const setCells = useCallback((next) => setCellsState(next), []);
  const setEnabled = useCallback((next) => setEnabledState(next), []);

  return { cells, setCells, enabled, setEnabled };
}
