import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import HearingTypeIcon from "../components/HearingTypeIcon.jsx";
import { CASE_CATEGORY_LABELS } from "../courtInfo.js";

// Only the two hearing-type buckets a topic can meaningfully target --
// "other"/"unrecognized" aren't real categories to write an explainer
// for (see app/models.py::HearingTypeCategory).
const HEARING_TYPE_LABELS = {
  jury_trial: "Jury Trial",
  oral_argument_motions: "Oral Argument / Motions Hearing",
};

function excerpt(text, max = 160) {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max).trim()}…` : text;
}

export default function Learn() {
  const [hearingTypeCategory, setHearingTypeCategory] = useState("");
  const [caseCategory, setCaseCategory] = useState("");
  const [topics, setTopics] = useState(null);
  const [error, setError] = useState(null);

  function load() {
    api
      .listLearnTopics({ hearing_type_category: hearingTypeCategory || undefined, case_category: caseCategory || undefined })
      .then(setTopics)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [hearingTypeCategory, caseCategory]);

  const caseCategoryEntries = Object.entries(CASE_CATEGORY_LABELS).filter(([k]) => k !== "juvenile");

  function toggle(current, setter, value) {
    setter(current === value ? "" : value);
  }

  return (
    <article>
      <header className="learn-header">
        <p className="learn-eyebrow">LEARN / 00</p>
        <h1 className="learn-headline">Understand What You're About to Watch</h1>
        <p style={{ color: "var(--ink-soft)" }}>
          Written by CUSG Justices, for anyone new to a courtroom.
        </p>
      </header>

      <div className="learn-pill-strip">
        {Object.entries(HEARING_TYPE_LABELS).map(([k, label]) => (
          <button
            key={k}
            className={`learn-pill ${hearingTypeCategory === k ? "active" : ""}`}
            onClick={() => toggle(hearingTypeCategory, setHearingTypeCategory, k)}
          >
            {label}
          </button>
        ))}
        {caseCategoryEntries.map(([k, label]) => (
          <button
            key={k}
            className={`learn-pill ${caseCategory === k ? "active" : ""}`}
            onClick={() => toggle(caseCategory, setCaseCategory, k)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="learn-body">
        <aside className="learn-sidebar">
          <div>
            <p className="learn-sidebar-heading">By Hearing Type</p>
            {Object.entries(HEARING_TYPE_LABELS).map(([k, label]) => (
              <button
                key={k}
                className={`learn-sidebar-link ${hearingTypeCategory === k ? "active" : ""}`}
                onClick={() => toggle(hearingTypeCategory, setHearingTypeCategory, k)}
              >
                <HearingTypeIcon type={k} /> {label}
              </button>
            ))}
          </div>
          <div>
            <p className="learn-sidebar-heading">By Case Category</p>
            {caseCategoryEntries.map(([k, label]) => (
              <button
                key={k}
                className={`learn-sidebar-link learn-sidebar-link-plain ${caseCategory === k ? "active" : ""}`}
                onClick={() => toggle(caseCategory, setCaseCategory, k)}
              >
                {label}
              </button>
            ))}
          </div>
        </aside>

        <div className="learn-grid">
          {error && <p className="message-error">{error}</p>}
          {!topics && !error && <p>Loading&hellip;</p>}
          {topics && topics.length === 0 && (
            <div className="empty-state">
              <p>No Learn topics match these filters yet.</p>
            </div>
          )}
          {topics?.map((t, i) => (
            <div className="learn-card" key={t.id}>
              <p className="learn-card-numeral">{String(i + 1).padStart(2, "0")}</p>
              <h2 className="learn-card-heading">{t.title}</h2>
              <p className="learn-card-excerpt">{excerpt(t.body_text)}</p>
              <div className="learn-card-meta">
                {(t.video_url || t.has_uploaded_video) && (
                  <span className="learn-card-meta-item">&#9654; Video included</span>
                )}
                {t.external_links.length > 0 && (
                  <span className="learn-card-meta-item">
                    {t.external_links.length} resource{t.external_links.length === 1 ? "" : "s"} linked
                  </span>
                )}
              </div>
              <Link to={`/learn/${t.id}`}>Read the full guide &rarr;</Link>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}
