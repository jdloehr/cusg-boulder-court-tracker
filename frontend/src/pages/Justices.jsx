import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

// Phase-3 doc, Section 3: "Meet the Justices" -- a public directory of
// all 7-8 profiles, each linking to its own page.
export default function Justices() {
  const [justices, setJustices] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listJustices().then(setJustices).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="message-error">{error}</p>;
  if (!justices) return <p>Loading&hellip;</p>;

  return (
    <article>
      <h1>Meet the Justices</h1>
      <p className="disclaimer">The CUSG Supreme Court's current roster.</p>
      <div className="justice-grid">
        {justices.map((j) => (
          <Link to={`/justices/${j.id}`} className="justice-card" key={j.id}>
            {j.photo_url ? (
              <img className="justice-photo" src={api.justicePhotoUrl(j.id)} alt="" />
            ) : (
              <div className="justice-photo-placeholder" aria-hidden="true">
                {(j.display_name || "?")[0]}
              </div>
            )}
            <strong>{j.display_name}</strong>
            {j.title && <div style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>{j.title}</div>}
          </Link>
        ))}
      </div>
    </article>
  );
}
