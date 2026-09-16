import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";

// Phase-3 doc, Section 3: an individual Justice's public profile page,
// at a stable URL (/justices/:id) -- this is also where a Justice's name
// links to from everywhere else on the site (see components/JusticeLink.jsx).
export default function JusticeProfile() {
  const { id } = useParams();
  const [justice, setJustice] = useState(null);
  const [error, setError] = useState(null);
  const admin = getStoredAdmin();

  useEffect(() => {
    setJustice(null);
    api.getJustice(id).then(setJustice).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="message-error">Couldn't load this profile: {error}</p>;
  if (!justice) return <p>Loading&hellip;</p>;

  const isMe = admin?.isJustice && admin.id === justice.id;

  return (
    <article>
      <p>
        <Link to="/justices">&larr; Meet the Justices</Link>
      </p>

      <div className="justice-profile-header">
        {justice.photo_url ? (
          <img className="justice-photo" src={api.justicePhotoUrl(justice.id)} alt="" />
        ) : (
          <div className="justice-photo-placeholder" aria-hidden="true">
            {(justice.display_name || "?")[0]}
          </div>
        )}
        <div>
          <h1 style={{ marginBottom: "0.2rem" }}>{justice.display_name}</h1>
          {justice.title && <p style={{ color: "var(--ink-soft)", marginTop: 0 }}>{justice.title}</p>}
          {justice.year_or_major && <p style={{ marginTop: "0.2rem" }}>{justice.year_or_major}</p>}
          {isMe && (
            <p style={{ marginTop: "0.5rem" }}>
              <Link to="/justices/me/edit" className="btn btn-secondary">
                Edit my profile
              </Link>
            </p>
          )}
        </div>
      </div>

      {justice.bio && (
        <div className="card">
          <h3>Bio</h3>
          <p className="blurb">{justice.bio}</p>
        </div>
      )}
      {justice.why_care && (
        <div className="card">
          <h3>Why I care about court-watching</h3>
          <p className="blurb">{justice.why_care}</p>
        </div>
      )}
      {justice.fun_fact && (
        <div className="card">
          <h3>Fun fact</h3>
          <p className="blurb">{justice.fun_fact}</p>
        </div>
      )}
      {!justice.bio && !justice.why_care && !justice.fun_fact && (
        <p style={{ color: "var(--ink-soft)" }}>This Justice hasn't filled out their profile yet.</p>
      )}
    </article>
  );
}
