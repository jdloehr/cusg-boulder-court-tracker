import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import { COURT_INFO, COURT_LOCATION_TAG } from "../courtInfo.js";
import JusticeLink from "../components/JusticeLink.jsx";

const ATTENDANCE_LABELS = {
  attending: "Attending",
  not_attending: "Not attending",
  maybe: "Maybe",
};

export default function HearingDetail() {
  const { id } = useParams();
  const [hearing, setHearing] = useState(null);
  const [error, setError] = useState(null);
  const admin = getStoredAdmin();

  function reload() {
    api.getHearing(id).then(setHearing).catch((e) => setError(e.message));
  }
  useEffect(reload, [id]);

  if (error) return <p className="message-error">Couldn't load this hearing: {error}</p>;
  if (!hearing) return <p>Loading&hellip;</p>;

  const info = COURT_INFO[hearing.court_location] || COURT_INFO.unknown;

  return (
    <article>
      <p>
        <Link to="/hearings">&larr; Back to all hearings</Link>
      </p>

      <div className="detail-header">
        <h1>{hearing.hearing_type_raw}</h1>
        {hearing.court_location !== "boulder_county" && (
          <span className="badge badge-federal">{COURT_LOCATION_TAG[hearing.court_location] || hearing.court_location}</span>
        )}
        {hearing.news_mentions?.length > 0 && <span className="badge badge-news">In the news</span>}
        {hearing.status === "changed" && <span className="badge badge-changed">Time/place changed</span>}
        {hearing.status === "cancelled" && <span className="badge badge-cancelled">Cancelled</span>}
      </div>

      <RecommendationCallout hearingId={hearing.id} />

      {hearing.status === "cancelled" && (
        <p className="banner">
          This hearing is no longer showing on the docket export as of the last check. It may have been
          cancelled, resolved, or continued to a date outside our tracking window. {hearing.change_note}
        </p>
      )}
      {hearing.status === "changed" && <p className="banner">{hearing.change_note}</p>}

      <p className="blurb">{hearing.hearing_type_display}</p>

      {hearing.curated_blurb && (
        <div className="card">
          <h3>Why watch this</h3>
          <p className="blurb">{hearing.curated_blurb}</p>
        </div>
      )}

      <dl className="fact-grid">
        <div>
          <dt>Date</dt>
          <dd>{new Date(hearing.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</dd>
        </div>
        <div>
          <dt>Time</dt>
          <dd>{hearing.time || "Not specified"}</dd>
        </div>
        <div>
          <dt>Estimated duration</dt>
          <dd>{hearing.duration || "Not specified"}</dd>
        </div>
        <div>
          <dt>Case number</dt>
          <dd>{hearing.case_number}</dd>
        </div>
        <div>
          <dt>Case category</dt>
          <dd style={{ textTransform: "capitalize" }}>{hearing.case_category.replace("_", " ")}</dd>
        </div>
        <div>
          <dt>Courtroom</dt>
          <dd>{hearing.courtroom || "TBD"}</dd>
        </div>
        <div>
          <dt>Judge</dt>
          <dd>{hearing.judge_name || "Not yet known"}</dd>
        </div>
        <div>
          <dt>In person?</dt>
          <dd style={{ textTransform: "capitalize" }}>{hearing.appearance_type.replace("_", " ")}</dd>
        </div>
        <div>
          <dt>Last verified</dt>
          <dd>{new Date(hearing.last_verified_at).toLocaleString()}</dd>
        </div>
      </dl>

      <div className="card">
        <h3>{info.name}</h3>
        <p>{info.address}</p>
        <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
          First time in a courthouse? See <Link to="/about">Visiting a Courtroom</Link> for what to expect
          (ID, security screening, phone policies).
        </p>
      </div>

      <CourtAttendance hearing={hearing} admin={admin} onChange={reload} />

      {hearing.news_mentions?.length > 0 && (
        <div className="card">
          <h3>News coverage</h3>
          <ul>
            {hearing.news_mentions.map((m) => (
              <li key={m.id}>
                <a href={m.article_url} target="_blank" rel="noreferrer">
                  {m.headline}
                </a>{" "}
                &mdash; {m.source_name}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hearing.community_submissions?.length > 0 && (
        <div className="card">
          <h3>Community notes</h3>
          {hearing.community_submissions.map((s) => (
            <p key={s.id} className="blurb">{s.summary_text}</p>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <a className="btn" href={api.icsUrl(hearing.id)}>
          Add to calendar (.ics)
        </a>
        <a
          className="btn btn-secondary"
          href={`https://www.coloradojudicial.gov/dockets?caseNumber=${encodeURIComponent(hearing.case_number)}`}
          target="_blank"
          rel="noreferrer"
        >
          Confirm on official docket
        </a>
        <LivestreamLink hearing={hearing} />
      </div>

      {hearing.date < new Date().toISOString().slice(0, 10) && <ArchiveSubmission hearing={hearing} admin={admin} />}

      <AddDetailsForm hearingId={hearing.id} onSubmitted={reload} />

      <p className="disclaimer" style={{ marginTop: "2rem" }}>
        This is a planning aid, not an authoritative record. Court schedules change often --
        confirm the date, time, and courtroom on the official docket the morning of, especially for
        anything more than a few days out.
      </p>
    </article>
  );
}

// Phase-2 doc, Section 2 + 7: honest, modestly-styled livestream link --
// never implies a guaranteed "watch now," since state-court streaming is
// judge's discretion (CJD 23-02) and federal courts rarely offer one at
// all. See app/livestream.py for how each source_type gets assigned.
const LIVESTREAM_LABELS = {
  state_portal: "May be livestreamed — check live.coloradojudicial.gov",
  scotus_audio: "Listen live (SCOTUS oral argument audio)",
  federal_audio_line: "Public audio access line",
};

function LivestreamLink({ hearing }) {
  const label = LIVESTREAM_LABELS[hearing.livestream_source_type];
  if (!label || !hearing.livestream_url) return null;
  return (
    <a className="btn btn-secondary" href={hearing.livestream_url} target="_blank" rel="noreferrer">
      {label}
    </a>
  );
}

// Phase-2 doc, Section 4: "a prominent star badge appears at the top of the
// hearing detail page ... should support multiple recommendations on the
// same hearing (show all of them, don't overwrite)." A top-of-page
// callout, not buried in a tab -- rendered right under the title/badges,
// before anything else.
function RecommendationCallout({ hearingId }) {
  const [recs, setRecs] = useState(null);

  useEffect(() => {
    api.listRecommendations(hearingId).then(setRecs).catch(() => setRecs([]));
  }, [hearingId]);

  if (!recs || recs.length === 0) return null;

  return (
    <div className="card recommendation-callout">
      {recs.map((r) => (
        <p key={r.id} style={{ margin: "0.25rem 0" }}>
          <span className="badge badge-news">&#9733; Recommended</span>{" "}
          <JusticeLink justiceId={r.justice_id}>
            <strong>{r.justice_title ? `${r.justice_title} ${r.justice_display_name}` : r.justice_display_name}</strong>
          </JusticeLink>
          {" recommends this case — “"}
          {r.note}
          {"”"}
        </p>
      ))}
    </div>
  );
}

function CourtAttendance({ hearing, admin, onChange }) {
  const [justices, setJustices] = useState(null);
  const [note, setNote] = useState("");
  const [recNote, setRecNote] = useState("");
  const [message, setMessage] = useState(null);

  useEffect(() => {
    api.listJustices().then(setJustices).catch(() => setJustices([]));
  }, []);

  const byId = new Map((hearing.attendance || []).map((a) => [a.justice_id, a]));
  const mine = admin?.isJustice ? hearing.attendance?.find((a) => a.display_name === admin.displayName) : null;

  // Pre-fill the note box from the already-saved note (once) rather than
  // always starting blank, so re-opening a hearing shows what was written
  // last time instead of looking like it was lost.
  useEffect(() => {
    if (mine?.note) setNote((current) => current || mine.note);
  }, [mine?.note]);

  async function setStatus(status) {
    await api.setAttendance(hearing.id, { status, note: note || undefined });
    onChange();
  }

  async function recommend() {
    if (!recNote.trim()) {
      setMessage("A reason is required.");
      return;
    }
    await api.createRecommendation({ hearing_id: hearing.id, note: recNote.trim() });
    setMessage("Added to the court recommendations board, and every Justice has been emailed.");
    setRecNote("");
    onChange();
  }

  if (justices === null) return null;

  return (
    <div className="card">
      <h3>Court attendance</h3>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
        Who from the court plans to be here.
      </p>
      <table className="data-table">
        <tbody>
          {justices.map((j) => {
            const a = byId.get(j.id);
            const isMe = admin?.isJustice && admin.displayName === j.display_name;
            return (
              <tr key={j.id}>
                <td>
                  <JusticeLink justiceId={j.id}>
                    {j.title ? `${j.title} ${j.display_name}` : j.display_name}
                  </JusticeLink>
                </td>
                <td>
                  {isMe ? (
                    <select value={a?.status || ""} onChange={(e) => setStatus(e.target.value)} style={{ minWidth: "10rem" }}>
                      <option value="" disabled>
                        No response yet -- click to set
                      </option>
                      <option value="attending">Attending</option>
                      <option value="maybe">Maybe</option>
                      <option value="not_attending">Not attending</option>
                    </select>
                  ) : a ? (
                    <span className={`badge ${a.status === "attending" ? "badge-news" : a.status === "maybe" ? "badge-changed" : "badge-cancelled"}`}>
                      {ATTENDANCE_LABELS[a.status]}
                    </span>
                  ) : (
                    <span style={{ color: "var(--ink-soft)", fontSize: "0.85rem" }}>No response yet</span>
                  )}
                  {a?.note && !isMe && <div style={{ fontSize: "0.82rem", color: "var(--ink-soft)" }}>{a.note}</div>}
                  {isMe && (
                    <input
                      placeholder="Optional note (e.g. conflicts with class until 2pm)"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      onBlur={() => a?.status && setStatus(a.status)}
                      style={{ display: "block", width: "100%", maxWidth: "22rem", marginTop: "0.4rem", fontSize: "0.85rem", padding: "0.3rem 0.5rem" }}
                    />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!admin?.isJustice && (
        <p style={{ fontSize: "0.82rem", color: "var(--ink-soft)", marginTop: "0.5rem" }}>
          <Link to="/admin/login">Sign in as a Justice</Link> to set your own status or recommend this hearing.
        </p>
      )}

      {admin?.isJustice && (
        <div style={{ marginTop: "1rem", borderTop: "1px solid var(--line)", paddingTop: "1rem" }}>
          <p style={{ fontSize: "0.85rem" }}>
            Recommend this hearing to the rest of the court (see the{" "}
            <Link to="/recommendations">recommendations board</Link>) -- a reason is required, and every
            Justice will be emailed:
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <input
              placeholder="Why is this worth the court's attention? (required)"
              value={recNote}
              onChange={(e) => setRecNote(e.target.value)}
              style={{ flex: 1, minWidth: "12rem" }}
            />
            <button className="btn btn-secondary" onClick={recommend} disabled={!recNote.trim()}>
              Recommend
            </button>
          </div>
          {message && <p className="message-success">{message}</p>}
        </div>
      )}
    </div>
  );
}

const STAGE_OPTIONS = [
  ["opening_statements", "Opening Statements"],
  ["closing_arguments", "Closing Arguments"],
  ["sentencing", "Sentencing"],
  ["oral_argument", "Oral Argument"],
  ["jury_selection", "Jury Selection"],
  ["motions_hearing", "Motions Hearing"],
  ["other", "Other"],
];

// Phase-2 doc, Section 3 + 5: "Mark Attendance" (a logged-in Justice,
// reflection optional) and "Submit a Summary" (anyone, no login,
// reflection required) both post to the same Archive endpoint -- see
// routers/archive.py for how the backend tells them apart. Restricted to
// hearings whose date has already passed (the page only renders this
// component for those -- see the date check in HearingDetail above).
function ArchiveSubmission({ hearing, admin }) {
  const [stage, setStage] = useState("other");
  const [judgeName, setJudgeName] = useState("");
  const [reflection, setReflection] = useState("");
  const [name, setName] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  const isJustice = admin?.isJustice;

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.createArchiveEntry({
        hearing_id: hearing.id,
        proceeding_stage: stage,
        judge_name: judgeName || undefined,
        reflection_text: reflection || undefined,
        submitted_by_name: name || "Anonymous",
        website: website || undefined,
      });
      setStatus({ ok: true, message: "Added to the Archive." });
      setReflection("");
      setJudgeName("");
    } catch (err) {
      setStatus({ ok: false, message: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginTop: "1.5rem" }}>
      <h3>{isJustice ? "Mark attendance / write a reflection" : "Were you there? Write it up for the Archive"}</h3>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
        {isJustice
          ? "You'll be added as an attendee. A reflection is optional."
          : "Publishes immediately under your name -- see the Archive."}
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="stage">What did you see?</label>
          <select id="stage" value={stage} onChange={(e) => setStage(e.target.value)}>
            {STAGE_OPTIONS.map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="archiveJudgeName">Judge (optional)</label>
          <input id="archiveJudgeName" value={judgeName} onChange={(e) => setJudgeName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="reflection">Reflection {isJustice ? "(optional)" : "(required)"}</label>
          <textarea
            id="reflection"
            value={reflection}
            onChange={(e) => setReflection(e.target.value)}
            required={!isJustice}
          />
        </div>
        {!isJustice && (
          <div>
            <label htmlFor="submittedByName">Your name</label>
            <input id="submittedByName" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        )}
        <div style={{ position: "absolute", left: "-9999px" }} aria-hidden="true">
          <label htmlFor="archiveWebsite">Leave blank</label>
          <input id="archiveWebsite" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
        </div>
        <button className="btn btn-secondary" type="submit" disabled={busy}>
          {busy ? "Submitting…" : isJustice ? "Mark attendance" : "Submit for the Archive"}
        </button>
        {status && <p className={status.ok ? "message-success" : "message-error"}>{status.message}</p>}
      </form>
    </div>
  );
}

function AddDetailsForm({ hearingId, onSubmitted }) {
  const [summary, setSummary] = useState("");
  const [judgeName, setJudgeName] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.submitDetails(hearingId, {
        summary_text: summary || undefined, judge_name: judgeName || undefined, website: website || undefined,
      });
      setStatus({ ok: true, message: "Thanks -- the team will review this before it appears." });
      setSummary("");
      setJudgeName("");
      onSubmitted();
    } catch (err) {
      setStatus({ ok: false, message: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginTop: "1.5rem" }}>
      <h3>Know something about this case?</h3>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
        Add a summary, the judge's name, or other details -- reviewed by the team before it appears publicly.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="summary">Summary / context</label>
          <textarea id="summary" value={summary} onChange={(e) => setSummary(e.target.value)} />
        </div>
        <div>
          <label htmlFor="judgeName">Judge's name</label>
          <input id="judgeName" value={judgeName} onChange={(e) => setJudgeName(e.target.value)} />
        </div>
        {/* Honeypot -- hidden from real visitors via CSS, not display:none (some bots skip those). */}
        <div style={{ position: "absolute", left: "-9999px" }} aria-hidden="true">
          <label htmlFor="website">Leave blank</label>
          <input id="website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
        </div>
        <button className="btn btn-secondary" type="submit" disabled={busy}>
          {busy ? "Submitting…" : "Submit for review"}
        </button>
        {status && <p className={status.ok ? "message-success" : "message-error"}>{status.message}</p>}
      </form>
    </div>
  );
}
