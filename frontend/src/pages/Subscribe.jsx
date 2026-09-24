import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import AvailabilityBlockEditor from "../components/AvailabilityBlockEditor.jsx";
import { useVisitorAvailability } from "../useVisitorAvailability.js";

export default function Subscribe() {
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [filterType, setFilterType] = useState("hearing_type_category");
  const [filterValue, setFilterValue] = useState("jury_trial");
  const [frequency, setFrequency] = useState("weekly_digest");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  // Phase-6.2 doc, Section 6: a visitor who already entered personal
  // availability (Section 5, browser-local) can turn it into a standing
  // email -- prefilled here rather than re-typed from scratch.
  const visitorAvailability = useVisitorAvailability();
  const [availabilityBlocks, setAvailabilityBlocks] = useState(visitorAvailability.blocks);

  useEffect(() => {
    if (searchParams.get("filterType") === "personal_availability") {
      onFilterTypeChange("personal_availability");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onFilterTypeChange(value) {
    setFilterType(value);
    if (value === "hearing_type_category") {
      setFilterValue("jury_trial");
      setFrequency("weekly_digest");
    } else if (value === "new_recommendation") {
      // Nothing to filter by -- filter_value is unused for this type
      // (see SubscriptionFilterType.new_recommendation in app/models.py).
      setFilterValue("all");
      setFrequency("realtime_for_followed_case");
    } else if (value === "personal_availability") {
      setFilterValue("n/a"); // unused for this type too, same reasoning
      setFrequency("weekly_digest");
      if (availabilityBlocks.length === 0) setAvailabilityBlocks(visitorAvailability.blocks);
    } else {
      setFilterValue("");
    }
  }

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.createSubscription({
        email,
        filter_type: filterType,
        filter_value: filterValue,
        frequency,
        availability_blocks: filterType === "personal_availability" ? availabilityBlocks : undefined,
      });
      setStatus({
        ok: true,
        message:
          filterType === "new_recommendation"
            ? "You're subscribed -- you'll get an email as soon as a Justice recommends a new hearing."
            : "You're subscribed. Look for the first digest next Monday.",
      });
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
        Email only, no account needed. Choose a weekly digest of hearings matching your filter,
        real-time alerts for one specific case you're following, or an alert the moment the court
        recommends a new hearing. Digests are shortened during CU breaks and finals week.
      </p>

      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="email">Email address</label>
          <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>

        <div>
          <label htmlFor="filterType">Follow by</label>
          <select id="filterType" value={filterType} onChange={(e) => onFilterTypeChange(e.target.value)}>
            <option value="hearing_type_category">Hearing type</option>
            <option value="case_number">A specific case number</option>
            <option value="keyword">Keyword</option>
            <option value="new_recommendation">New court recommendations</option>
            <option value="personal_availability">My personal availability</option>
          </select>
        </div>

        {filterType === "hearing_type_category" && (
          <div>
            <label htmlFor="filterValue">Type</label>
            <select id="filterValue" value={filterValue} onChange={(e) => setFilterValue(e.target.value)}>
              <option value="jury_trial">Jury trials</option>
              <option value="oral_argument_motions">Oral arguments / motions</option>
            </select>
          </div>
        )}
        {(filterType === "case_number" || filterType === "keyword") && (
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
        {filterType === "new_recommendation" && (
          <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
            You'll get an email every time a Justice adds one -- see the{" "}
            <a href="/recommendations">recommendations board</a>.
          </p>
        )}
        {filterType === "personal_availability" && (
          <div>
            <label>Your free time</label>
            <p className="disclaimer" style={{ margin: "0 0 0.75rem" }}>
              We'll only email you about hearings that overlap one of these blocks.
            </p>
            <AvailabilityBlockEditor blocks={availabilityBlocks} onChange={setAvailabilityBlocks} />
          </div>
        )}

        {filterType !== "new_recommendation" && filterType !== "personal_availability" && (
          <div>
            <label htmlFor="frequency">Frequency</label>
            <select id="frequency" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
              <option value="weekly_digest">Weekly digest</option>
              <option value="realtime_for_followed_case">
                Real-time (only meaningful when following a specific case number)
              </option>
            </select>
          </div>
        )}

        <button
          className="btn"
          type="submit"
          disabled={busy || (filterType === "personal_availability" && availabilityBlocks.length === 0)}
        >
          {busy ? "Subscribing…" : "Subscribe"}
        </button>

        {status && (
          <p className={status.ok ? "message-success" : "message-error"}>{status.message}</p>
        )}
      </form>
    </article>
  );
}
