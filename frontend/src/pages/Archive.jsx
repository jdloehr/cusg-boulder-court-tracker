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

// Page-redesign doc, Page 3: a warm, hand-placed "paper" timeline rather
// than a plain list -- accent color and card rotation are computed here
// from each entry's position, not stored, so they stay consistent
// (never two consecutive entries sharing a color) no matter how many
// real entries the backend returns.
const ACCENT_CYCLE = ["terracotta", "sage", "ochre", "plum"];
const ROTATIONS = [-0.4, 0.3];
const PAGE_SIZE = 10;

export default function Archive() {
  const [stage, setStage] = useState("");
  const [caseCategory, setCaseCategory] = useState("");
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const admin = getStoredAdmin();

  function load() {
    api
      .listArchive({ proceeding_stage: stage || undefined, case_category: caseCategory || undefined })
      .then(setEntries)
      .catch((e) => setError(e.message));
  }
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage, caseCategory]);

  async function remove(id) {
    await api.deleteArchiveEntry(id);
    load();
  }

  const visible = entries?.slice(0, visibleCount) || [];

  return (
    <article>
      <header className="archive-header">
        <p className="archive-eyebrow">CUSG Judicial Branch Archive</p>
        <h1 className="archive-headline">Where the Court Has Been</h1>
        <p style={{ color: "var(--ink-soft)" }}>
          A record of hearings the court -- and anyone else who went -- actually attended and wrote up.
        </p>
        <div className="archive-gradient-bar" />
      </header>

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

      <div className="archive-timeline">
        {visible.map((e, i) => {
          const accent = ACCENT_CYCLE[i % ACCENT_CYCLE.length];
          const rotation = ROTATIONS[i % ROTATIONS.length];
          return (
            <div className="archive-timeline-item" key={e.id}>
              <span className={`archive-timeline-dot archive-accent-${accent}`} />
              <article
                className={`archive-card archive-accent-border-${accent}`}
                style={{ transform: `rotate(${rotation}deg)` }}
              >
                <div className="archive-card-body">
                  <div className={`archive-card-photo archive-accent-gradient-${accent}`} aria-hidden="true" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <h2 style={{ margin: "0 0 0.2rem" }}>
                      <Link to={`/hearings/${e.hearing_id}`}>{e.hearing_type_display?.split(":")[0] || "Hearing"}</Link>
                    </h2>
                    <p className="archive-entry-meta" style={{ margin: "0 0 0.4rem" }}>
                      {e.hearing_date} &middot; Case {e.hearing_case_number}
                    </p>
                    <span className="badge badge-category">{STAGE_LABELS[e.proceeding_stage]}</span>
                    {e.reflection_text && <p className="archive-card-quote">&ldquo;{e.reflection_text}&rdquo;</p>}
                    <div className="archive-card-byline">
                      <span>{e.judge_name ? `${e.judge_name} presiding` : ""}</span>
                      <span className="archive-card-byline-author">
                        {e.submitted_by_role === "justice" ? "Justice " : ""}
                        <JusticeLink justiceId={e.submitted_by_justice_id}>{e.submitted_by_name}</JusticeLink>
                      </span>
                    </div>
                    {e.attendees?.length > 0 && (
                      <p style={{ fontSize: "0.8rem", color: "var(--ink-soft)", margin: "0.3rem 0 0" }}>
                        Attended by{" "}
                        {e.attendees.map((a, j) => (
                          <Fragment key={a.name + j}>
                            {j > 0 && ", "}
                            <JusticeLink justiceId={a.justice_id}>{a.name}</JusticeLink>
                          </Fragment>
                        ))}
                      </p>
                    )}
                    <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.75rem", alignItems: "center" }}>
                      {admin?.isJustice && (
                        <button className="btn btn-danger" onClick={() => remove(e.id)}>
                          Remove
                        </button>
                      )}
                      <ReportLink targetType="archive_entry" targetId={e.id} />
                    </div>
                  </div>
                </div>
              </article>
            </div>
          );
        })}
      </div>

      {entries && visibleCount < entries.length && (
        <p style={{ textAlign: "center" }}>
          <button className="btn btn-secondary" onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
            Show more
          </button>
        </p>
      )}
    </article>
  );
}
