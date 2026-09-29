import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import JusticeLink from "../components/JusticeLink.jsx";
import ReportLink from "../components/ReportLink.jsx";

// Page-redesign doc: "What the Court Is Watching" -- an editorial digest
// masthead rather than a flat list. The Lead card is whichever
// recommendation a Justice has pinned (HearingRecommendation.is_pinned,
// "exactly one row True at a time" -- see routers/justices.py::
// pin_recommendation); everything else renders in the secondary grid,
// most recent first (the existing server-side sort, unchanged).
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
  async function pin(id) {
    await api.pinRecommendation(id);
    load();
  }
  async function unpin(id) {
    await api.unpinRecommendation(id);
    load();
  }

  if (error) return <p className="message-error">{error}</p>;
  if (!recs) return <p>Loading&hellip;</p>;

  const lead = recs.find((r) => r.is_pinned);
  const rest = recs.filter((r) => r.id !== lead?.id);

  return (
    <article>
      <div className="rec-masthead">
        <div className="rec-masthead-row">
          <div>
            <p className="rec-masthead-eyebrow">CUSG Court Digest</p>
            <h1 className="rec-masthead-headline">What the Court Is Watching</h1>
          </div>
          <p className="rec-masthead-subhead">
            Hand-picked by the Justices -- hearings worth the rest of the court's attention, with a
            reason why.
          </p>
        </div>
      </div>

      {recs.length === 0 && (
        <div className="empty-state">
          <p>No recommendations yet.</p>
        </div>
      )}

      {lead && <LeadCard rec={lead} admin={admin} onUnpin={() => unpin(lead.id)} onRemove={() => remove(lead.id)} />}

      {rest.length > 0 && (
        <>
          <p className="rec-section-label">More Picks From the Bench</p>
          <div className="rec-grid">
            {rest.map((r, i) => (
              <RecCard
                key={r.id}
                rec={r}
                numeral={String(i + 1).padStart(2, "0")}
                big={i === 0}
                admin={admin}
                onPin={() => pin(r.id)}
                onRemove={() => remove(r.id)}
              />
            ))}
            <div className="rec-card rec-card-cta">
              <h3>Have a case in mind?</h3>
              <p>Justices can recommend any hearing from its own detail page, with a reason why.</p>
              {!admin?.isJustice && (
                <Link to="/admin/login" className="btn btn-navy">
                  Justice Sign In
                </Link>
              )}
            </div>
          </div>
        </>
      )}
    </article>
  );
}

function LeadCard({ rec, admin, onUnpin, onRemove }) {
  return (
    <div className="rec-lead">
      <p className="rec-lead-label">&#9733; Lead Recommendation</p>
      <h2 className="rec-lead-quote">&ldquo;{rec.note}&rdquo;</h2>
      <p className="rec-lead-meta">
        {rec.hearing_date} &middot; Case {rec.hearing_case_number}
      </p>
      <p>
        <Link to={`/hearings/${rec.hearing_id}`} className="btn">
          View Hearing Details
        </Link>
      </p>
      <div className="rec-lead-byline">
        <div className="rec-avatar" aria-hidden="true" />
        <div>
          <p style={{ margin: 0, fontWeight: 600 }}>
            <JusticeLink justiceId={rec.justice_id}>
              {rec.justice_title ? `${rec.justice_title} ${rec.justice_display_name}` : rec.justice_display_name}
            </JusticeLink>
          </p>
          <p style={{ margin: 0, fontSize: "0.8rem", color: "#c9d2da" }}>Recommended {rec.created_at?.slice(0, 10)}</p>
        </div>
      </div>
      {admin?.isJustice && (
        <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem" }}>
          <button className="btn btn-secondary" onClick={onUnpin}>Unpin</button>
          <button className="btn btn-danger" onClick={onRemove}>Remove</button>
        </div>
      )}
      <div style={{ marginTop: "0.5rem" }}>
        <ReportLink targetType="recommendation" targetId={rec.id} />
      </div>
    </div>
  );
}

function RecCard({ rec, numeral, big, admin, onPin, onRemove }) {
  return (
    <div className={`rec-card ${big ? "rec-card-big" : ""}`}>
      <p className="rec-card-numeral">{numeral}</p>
      <h3>
        <Link to={`/hearings/${rec.hearing_id}`}>{rec.hearing_type_display?.split(":")[0] || "Hearing"}</Link>
      </h3>
      {rec.note && <p className="rec-card-quote">&ldquo;{rec.note}&rdquo;</p>}
      <div className="rec-card-footer">
        <div className="rec-card-byline">
          <div className="rec-avatar rec-avatar-sm" aria-hidden="true" />
          <JusticeLink justiceId={rec.justice_id}>{rec.justice_display_name}</JusticeLink>
        </div>
        <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--ink-soft)" }}>
          {rec.hearing_date} &middot; Case {rec.hearing_case_number}
        </p>
      </div>
      {admin?.isJustice && (
        <div style={{ marginTop: "0.6rem", display: "flex", gap: "0.5rem" }}>
          <button className="btn btn-secondary" onClick={onPin}>Pin as lead</button>
          <button className="btn btn-danger" onClick={onRemove}>Remove</button>
        </div>
      )}
      <div style={{ marginTop: "0.4rem" }}>
        <ReportLink targetType="recommendation" targetId={rec.id} />
      </div>
    </div>
  );
}
