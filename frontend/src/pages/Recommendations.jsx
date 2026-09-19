import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import JusticeLink from "../components/JusticeLink.jsx";
import ReportLink from "../components/ReportLink.jsx";

export default function Recommendations() {
  const [recs, setRecs] = useState(null);
  const [error, setError] = useState(null);
  const admin = getStoredAdmin();

  function load() {
    api.listRecommendations().then(setRecs).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function remove(id) {
    await api.deleteRecommendation(id);
    load();
  }

  return (
    <article>
      <h1>Court Recommendations</h1>
      <p className="disclaimer">
        Hearings a CUSG Justice has personally flagged for the rest of the court, with a reason why.
        Add one from any hearing's detail page (Justice login required).
      </p>

      {error && <p className="message-error">{error}</p>}
      {!recs && !error && <p>Loading&hellip;</p>}
      {recs && recs.length === 0 && (
        <div className="empty-state">
          <p>No recommendations yet.</p>
        </div>
      )}

      {recs?.map((r) => (
        <div className="card" key={r.id}>
          <h3>
            <Link to={`/hearings/${r.hearing_id}`}>{r.hearing_type_display?.split(":")[0] || "Hearing"}</Link>
          </h3>
          <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
            Case {r.hearing_case_number} &middot; {r.hearing_date} &middot; recommended by{" "}
            <JusticeLink justiceId={r.justice_id}>
              {r.justice_title ? `${r.justice_title} ${r.justice_display_name}` : r.justice_display_name}
            </JusticeLink>
          </p>
          {r.note && <p className="blurb">{r.note}</p>}
          {admin?.isJustice && (
            <button className="btn btn-danger" onClick={() => remove(r.id)}>
              Remove
            </button>
          )}
          <div style={{ marginTop: "0.5rem" }}>
            <ReportLink targetType="recommendation" targetId={r.id} />
          </div>
        </div>
      ))}
    </article>
  );
}
