import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import JusticeLink from "../components/JusticeLink.jsx";
import ReportLink from "../components/ReportLink.jsx";

const STAGE_LABELS = {
  opening_statements: "Opening Statements",
  closing_arguments: "Closing Arguments",
  sentencing: "Sentencing",
  oral_argument: "Oral Argument",
  jury_selection: "Jury Selection",
  motions_hearing: "Motions Hearing",
  other: "Other",
};

const CASE_CATEGORY_LABELS = {
  criminal: "Criminal (felony)",
  misdemeanor: "Misdemeanor",
  traffic: "Traffic",
  civil: "Civil",
  domestic_relations: "Domestic Relations",
  probate: "Probate",
  other: "Other",
};

export default function Archive() {
  const [stage, setStage] = useState("");
  const [caseCategory, setCaseCategory] = useState("");
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);
  const admin = getStoredAdmin();

  function load() {
    api
      .listArchive({ proceeding_stage: stage || undefined, case_category: caseCategory || undefined })
      .then(setEntries)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [stage, caseCategory]);

  async function remove(id) {
    await api.deleteArchiveEntry(id);
    load();
  }

  return (
    <article>
      <h1>Archive &amp; Reflections</h1>
      <p className="disclaimer">
        A record of hearings the court -- and anyone else who went -- actually attended and wrote up.
        Separate from the upcoming-hearings calendar; this is what happened, told by whoever was there.
      </p>

      <div className="filter-bar">
        <div className="filter-field">
          <label htmlFor="a-stage">Proceeding stage</label>
          <select id="a-stage" value={stage} onChange={(e) => setStage(e.target.value)}>
            <option value="">All</option>
            {Object.entries(STAGE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="a-category">Case category</label>
          <select id="a-category" value={caseCategory} onChange={(e) => setCaseCategory(e.target.value)}>
            <option value="">All</option>
            {Object.entries(CASE_CATEGORY_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="message-error">{error}</p>}
      {!entries && !error && <p>Loading&hellip;</p>}
      {entries && entries.length === 0 && (
        <div className="empty-state">
          <p>Nothing here yet -- write up a hearing you attended from its detail page.</p>
        </div>
      )}

      {entries?.map((e) => (
        <article className="archive-entry" key={e.id}>
          <h2>
            <Link to={`/hearings/${e.hearing_id}`}>{e.hearing_type_display?.split(":")[0] || "Hearing"}</Link>
          </h2>
          <p className="archive-entry-meta">
            {STAGE_LABELS[e.proceeding_stage]} &middot; Case {e.hearing_case_number} &middot; {e.hearing_date}
            {e.judge_name ? ` · ${e.judge_name} presiding` : ""}
          </p>
          {e.reflection_text && <p className="archive-entry-body">{e.reflection_text}</p>}
          <p className="archive-entry-byline">
            {e.submitted_by_role === "justice" ? "Justice " : ""}
            <JusticeLink justiceId={e.submitted_by_justice_id}>{e.submitted_by_name}</JusticeLink>
            {e.attendees?.length > 0 && (
              <>
                {" · attended by "}
                {e.attendees.map((a, i) => (
                  <Fragment key={a.name + i}>
                    {i > 0 && ", "}
                    <JusticeLink justiceId={a.justice_id}>{a.name}</JusticeLink>
                  </Fragment>
                ))}
              </>
            )}
          </p>
          {admin?.isJustice && (
            <button className="btn btn-danger" onClick={() => remove(e.id)}>
              Remove
            </button>
          )}
          <div style={{ marginTop: "0.5rem" }}>
            <ReportLink targetType="archive_entry" targetId={e.id} />
          </div>
        </article>
      ))}
    </article>
  );
}
