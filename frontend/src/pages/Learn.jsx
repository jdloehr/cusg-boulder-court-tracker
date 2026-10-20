import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import HearingTypeIcon from "../components/HearingTypeIcon.jsx";
import MountainStrip from "../components/MountainStrip.jsx";
import { CASE_CATEGORY_LABELS } from "../courtInfo.js";

// jury_trial -> navy (hearingTypeVisuals.js), oral_argument_motions ->
// sage. A LearnTopic can only ever target these 2 real categories (see
// app/models.py::HearingTypeCategory), so this page never needs
// Sentencing/Closing Arguments treatment at all.
const HEARING_TYPE_CARD_COLOR = {
  jury_trial: "navy",
  oral_argument_motions: "sage",
};

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
  const [generalOnly, setGeneralOnly] = useState(false);
  const [topics, setTopics] = useState(null);
  const [error, setError] = useState(null);

  function load() {
    api
      .listLearnTopics(
        generalOnly
          ? { general_only: true }
          : { hearing_type_category: hearingTypeCategory || undefined, case_category: caseCategory || undefined }
      )
      .then(setTopics)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [hearingTypeCategory, caseCategory, generalOnly]);

  const caseCategoryEntries = Object.entries(CASE_CATEGORY_LABELS).filter(([k]) => k !== "juvenile");

  function toggle(current, setter, value) {
    setter(current === value ? "" : value);
    setGeneralOnly(false);
  }

  function toggleGeneral() {
    setGeneralOnly((g) => !g);
    setHearingTypeCategory("");
    setCaseCategory("");
  }

  return (
    <article>
      {/* Oct 2026 review, Phase 4 item 10: removed the "LEARN / 00"
          label (a meaningless numeral -- there's only ever one Learn
          page, nothing it's "0 of"). */}
      <header className="learn-header">
        <h1 className="learn-headline">Learn the room before you walk in</h1>
        <p className="learn-header-subhead">
          Short guides on what happens in a courtroom, what to wear, where to sit, and how to
          write up what you saw -- written by Justices, for anyone new to a courtroom.
        </p>
        <MountainStrip backColor="#6F7F55" slab1Color="#465331" slab2Color="#5B6944" slab3Color="#3B4829" />
      </header>

      {/* Oct 2026 review, Phase 4 item 10: removed this whole chip row
          -- it duplicated the exact same filter buttons already in
          .learn-sidebar below, just in a different shape. */}

      <div className="learn-body">
        <aside className="learn-sidebar">
          <div>
            <p className="learn-sidebar-heading">By Hearing Type</p>
            <button
              className={`learn-type-pill learn-type-pill-muted ${generalOnly ? "active" : ""}`}
              onClick={toggleGeneral}
            >
              General guides
            </button>
            {Object.entries(HEARING_TYPE_LABELS).map(([k, label]) => (
              <button
                key={k}
                className={`learn-type-pill learn-type-pill-${HEARING_TYPE_CARD_COLOR[k]} ${hearingTypeCategory === k ? "active" : ""}`}
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
          {topics?.map((t) => {
            const color = HEARING_TYPE_CARD_COLOR[t.applies_to_hearing_type_category] || null;
            return (
              <div className={`learn-card ${color ? `learn-card-${color}` : ""}`} key={t.id}>
                {color && (
                  <div className="learn-card-header">
                    <span className="learn-card-icon">
                      <HearingTypeIcon type={t.applies_to_hearing_type_category} />
                    </span>
                    <h2 className="learn-card-heading">{t.title}</h2>
                  </div>
                )}
                <div className="learn-card-body">
                  {!color && <h2 className="learn-card-heading">{t.title}</h2>}
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
              </div>
            );
          })}
          {topics && topics.length > 0 && (
            <div className="learn-card learn-card-checklist">
              <h3>Your first visit checklist</h3>
              <p>Photo ID, quiet phone, a notebook, and thirty minutes to spare for security.</p>
              <Link to="/about" className="btn">Open the checklist</Link>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
