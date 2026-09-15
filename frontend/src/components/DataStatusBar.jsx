import { useEffect, useState } from "react";
import { api } from "../api.js";

// Phase-2 doc, Section 1 + 7: "place it unobtrusively near the top of the
// calendar view as a small, secondary-style element -- it shouldn't
// visually compete with the hearing content itself." Global, not
// per-user: the refresh button updates the same shared timestamp everyone
// sees, gated by a server-side cooldown (not a per-visitor state).
export default function DataStatusBar({ onRefreshed }) {
  const [status, setStatus] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState(null);

  function load() {
    api.dataStatus().then(setStatus).catch(() => setStatus(null));
  }
  useEffect(load, []);

  async function refresh() {
    setRefreshing(true);
    setMessage(null);
    try {
      await api.triggerRefresh();
      setMessage("Refreshing… this can take up to a minute against the live docket. Reloading shortly.");
      // The refresh runs in the background server-side; give it a
      // realistic amount of time before checking for a new timestamp
      // and re-fetching the hearing list.
      setTimeout(() => {
        load();
        onRefreshed?.();
      }, 15000);
    } catch (err) {
      setMessage(err.message);
    } finally {
      setRefreshing(false);
    }
  }

  if (!status) return null;

  const cooldownActive = status.next_refresh_available_at && new Date(status.next_refresh_available_at) > new Date();
  const lastUpdatedText = status.last_updated_at
    ? new Date(status.last_updated_at).toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      })
    : "never yet";

  return (
    <div className="data-status-bar">
      <span>Last updated {lastUpdatedText}</span>
      <button
        className="btn btn-secondary data-status-refresh-btn"
        onClick={refresh}
        disabled={refreshing || cooldownActive}
        title={cooldownActive ? `Try again after ${new Date(status.next_refresh_available_at).toLocaleTimeString()}` : "Pull the latest docket data now"}
      >
        {refreshing ? "Refreshing…" : "Refresh now"}
      </button>
      {message && <span style={{ fontSize: "0.8rem" }}>{message}</span>}
    </div>
  );
}
