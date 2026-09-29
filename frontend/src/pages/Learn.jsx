import { useEffect, useState } from "react";
import { api } from "../api.js";
import VideoEmbed from "../components/VideoEmbed.jsx";
import { CASE_CATEGORY_LABELS } from "../courtInfo.js";

// Only the two hearing-type buckets a topic can meaningfully target --
// "other"/"unrecognized" aren't real categories to write an explainer
// for (see app/models.py::HearingTypeCategory).
const HEARING_TYPE_LABELS = {
  jury_trial: "Jury Trial",
  oral_argument_motions: "Oral Argument / Motions Hearing",
};

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

  return (
    <article>
      <h1>Learn</h1>
      <p className="disclaimer">
        New to court and not sure what you're looking at? These explainers cover what a kind of
        hearing or case actually is -- written by CUSG Justices. For something unusual about one
        specific case, look for "A Justice's Note on This Case" on that hearing's own page instead.
      </p>

      <div className="filter-bar">
        <div className="filter-field">
          <label htmlFor="l-type">Hearing type</label>
          <select id="l-type" value={hearingTypeCategory} onChange={(e) => setHearingTypeCategory(e.target.value)}>
            <option value="">All</option>
            {Object.entries(HEARING_TYPE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="l-case">Case category</label>
          <select id="l-case" value={caseCategory} onChange={(e) => setCaseCategory(e.target.value)}>
            <option value="">All</option>
            {Object.entries(CASE_CATEGORY_LABELS)
              .filter(([k]) => k !== "juvenile")
              .map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
          </select>
        </div>
      </div>

      {error && <p className="message-error">{error}</p>}
      {!topics && !error && <p>Loading&hellip;</p>}
      {topics && topics.length === 0 && (
        <div className="empty-state">
          <p>No Learn topics match these filters yet.</p>
        </div>
      )}

      {topics?.map((t) => (
        <div className="card" key={t.id}>
          <h3>
            {t.title}{" "}
            {t.applies_to_hearing_type_category && (
              <span className="badge badge-category">{HEARING_TYPE_LABELS[t.applies_to_hearing_type_category]}</span>
            )}{" "}
            {t.applies_to_case_category && (
              <span className="badge badge-category">{CASE_CATEGORY_LABELS[t.applies_to_case_category]}</span>
            )}
          </h3>
          <p className="blurb">{t.body_text}</p>
          <VideoEmbed
            videoUrl={t.video_url}
            uploadedVideoUrl={t.has_uploaded_video ? api.learnTopicVideoUrl(t.id) : null}
          />
          {t.external_links.length > 0 && (
            <ul>
              {t.external_links.map((link, i) => (
                <li key={i}>
                  <a href={link.url} target="_blank" rel="noreferrer">{link.label}</a>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </article>
  );
}
