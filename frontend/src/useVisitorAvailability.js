import { useCallback, useEffect, useState } from "react";

// Phase-6.2 doc, Section 5: a visitor's personal availability, stored
// browser-local only unless they explicitly subscribe (Section 6) --
// no server-side record of it exists by default. Follows this codebase's
// existing flat, `cusg_`-prefixed localStorage convention (see api.js),
// wrapped in try/catch for private-browsing tolerance.
const BLOCKS_KEY = "cusg_visitor_availability";
const ENABLED_KEY = "cusg_visitor_availability_enabled";

function readBlocks() {
  try {
    const raw = localStorage.getItem(BLOCKS_KEY);
    return raw ? JSON.parse(raw) : [];
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
  const [blocks, setBlocksState] = useState(readBlocks);
  const [enabled, setEnabledState] = useState(readEnabled);

  useEffect(() => {
    try {
      localStorage.setItem(BLOCKS_KEY, JSON.stringify(blocks));
    } catch {
      /* localStorage unavailable (e.g. private browsing) -- just don't persist */
    }
  }, [blocks]);

  useEffect(() => {
    try {
      localStorage.setItem(ENABLED_KEY, enabled ? "true" : "false");
    } catch {
      /* ignore */
    }
  }, [enabled]);

  const setBlocks = useCallback((next) => setBlocksState(next), []);
  const setEnabled = useCallback((next) => setEnabledState(next), []);

  return { blocks, setBlocks, enabled, setEnabled };
}
