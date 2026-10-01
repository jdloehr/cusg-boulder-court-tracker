import { useState } from "react";
import { api } from "../api.js";

// Calendar-sync doc: "Connect Google Calendar" on a Justice's own
// profile. Scope is freebusy-only (app/routers/google_calendar.py) --
// this app can never see an event's title, guests, or any other detail,
// enforced by the scope Google grants, not just this page's wording.
// No calendar picker (Google's own API docs confirm listing calendars
// needs the much broader calendar.readonly scope) -- syncs "primary" by
// default, with an optional manual calendar-ID field for anything else.
export default function GoogleCalendarSync({ status, onChange }) {
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [calendarId, setCalendarId] = useState("");
  const [calendarIdBusy, setCalendarIdBusy] = useState(false);
  const [calendarIdStatus, setCalendarIdStatus] = useState(null);
  const [error, setError] = useState(null);

  async function connect() {
    setConnecting(true);
    setError(null);
    try {
      const { authorization_url } = await api.googleCalendarConnect();
      // A real top-level browser navigation, not a fetch -- Google's own
      // login/consent screen has to render as the actual page.
      window.location.href = authorization_url;
    } catch (err) {
      setError(err.message);
      setConnecting(false);
    }
  }

  async function disconnect() {
    setDisconnecting(true);
    setError(null);
    try {
      await api.googleCalendarDisconnect();
      onChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setDisconnecting(false);
    }
  }

  async function saveCalendarId(e) {
    e.preventDefault();
    setCalendarIdBusy(true);
    setCalendarIdStatus(null);
    try {
      await api.googleCalendarSetCalendarId(calendarId);
      setCalendarIdStatus({ ok: true, message: "Calendar ID updated." });
    } catch (err) {
      setCalendarIdStatus({ ok: false, message: err.message });
    } finally {
      setCalendarIdBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginTop: "1.5rem" }}>
      <h3>Google Calendar sync</h3>
      <p className="disclaimer" style={{ margin: "0 0 1rem" }}>
        Link a Google Calendar instead of painting availability by hand. Only whether a time block
        is free or busy is ever shared -- never an event's title, guests, or any other detail,
        enforced by the specific Google permission requested, not just this page saying so.
      </p>

      {error && <p className="message-error">{error}</p>}

      {status.connected ? (
        <>
          <p className="message-success" style={{ marginBottom: "0.5rem" }}>
            Connected.{" "}
            {status.lastSyncedAt
              ? `Last synced ${new Date(status.lastSyncedAt).toLocaleString()}.`
              : "Not synced yet -- the next daily sync will pick it up."}
          </p>
          {status.lastSyncError && (
            <p className="message-error">
              Last sync failed: {status.lastSyncError}. Your last-known availability is kept as-is
              until a sync succeeds again.
            </p>
          )}
          <form onSubmit={saveCalendarId} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end", marginBottom: "0.75rem" }}>
            <div style={{ flex: 1 }}>
              <label htmlFor="gcalCalendarId">Calendar ID (optional -- defaults to your primary calendar)</label>
              <input
                id="gcalCalendarId"
                placeholder="primary"
                value={calendarId}
                onChange={(e) => setCalendarId(e.target.value)}
              />
            </div>
            <button className="btn btn-secondary" type="submit" disabled={calendarIdBusy}>
              {calendarIdBusy ? "Saving…" : "Update"}
            </button>
          </form>
          {calendarIdStatus && (
            <p className={calendarIdStatus.ok ? "message-success" : "message-error"}>{calendarIdStatus.message}</p>
          )}
          <button className="btn btn-danger" onClick={disconnect} disabled={disconnecting}>
            {disconnecting ? "Disconnecting…" : "Disconnect"}
          </button>
        </>
      ) : (
        <button className="btn" onClick={connect} disabled={connecting}>
          {connecting ? "Connecting…" : "Connect Google Calendar"}
        </button>
      )}
    </div>
  );
}
