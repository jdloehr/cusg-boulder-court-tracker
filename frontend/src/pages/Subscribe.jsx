import { useState } from "react";
import { api } from "../api.js";

export default function Subscribe() {
  const [email, setEmail] = useState("");
  const [filterType, setFilterType] = useState("hearing_type_category");
  const [filterValue, setFilterValue] = useState("jury_trial");
  const [frequency, setFrequency] = useState("weekly_digest");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.createSubscription({ email, filter_type: filterType, filter_value: filterValue, frequency });
      setStatus({ ok: true, message: "You're subscribed. Look for the first digest next Monday." });
      setEmail("");
    } catch (err) {
      setStatus({ ok: false, message: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <h1>Subscribe</h1>
      <p className="disclaimer">
        Email only, no account needed. Choose a weekly digest of hearings matching your filter, or
        real-time alerts for one specific case you're following. Digests are shortened during CU
        breaks and finals week.
      </p>

      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="email">Email address</label>
          <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>

        <div>
          <label htmlFor="filterType">Follow by</label>
          <select
            id="filterType"
            value={filterType}
            onChange={(e) => {
              setFilterType(e.target.value);
              setFilterValue(e.target.value === "hearing_type_category" ? "jury_trial" : "");
              if (e.target.value === "realtime_case") setFrequency("realtime_for_followed_case");
            }}
          >
            <option value="hearing_type_category">Hearing type</option>
            <option value="case_number">A specific case number</option>
            <option value="keyword">Keyword</option>
          </select>
        </div>

        {filterType === "hearing_type_category" ? (
          <div>
            <label htmlFor="filterValue">Type</label>
            <select id="filterValue" value={filterValue} onChange={(e) => setFilterValue(e.target.value)}>
              <option value="jury_trial">Jury trials</option>
              <option value="oral_argument_motions">Oral arguments / motions</option>
            </select>
          </div>
        ) : (
          <div>
            <label htmlFor="filterValue">{filterType === "case_number" ? "Case number" : "Keyword"}</label>
            <input
              id="filterValue"
              required
              placeholder={filterType === "case_number" ? "e.g. 2026CR001452" : "e.g. climate"}
              value={filterValue}
              onChange={(e) => setFilterValue(e.target.value)}
            />
          </div>
        )}

        <div>
          <label htmlFor="frequency">Frequency</label>
          <select id="frequency" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
            <option value="weekly_digest">Weekly digest</option>
            <option value="realtime_for_followed_case">
              Real-time (only meaningful when following a specific case number)
            </option>
          </select>
        </div>

        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Subscribing…" : "Subscribe"}
        </button>

        {status && (
          <p className={status.ok ? "message-success" : "message-error"}>{status.message}</p>
        )}
      </form>
    </article>
  );
}
