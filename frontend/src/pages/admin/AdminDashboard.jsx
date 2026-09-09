import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, clearAdmin, getStoredAdmin } from "../../api.js";

const TABS = [
  { key: "hearings", label: "Review Queue: Hearings" },
  { key: "news", label: "Review Queue: News" },
  { key: "community", label: "Review Queue: Community" },
  { key: "federal", label: "Appellate Supplement" },
  { key: "calendar", label: "Academic Calendar" },
  { key: "activity", label: "Activity Log" },
];

export default function AdminDashboard() {
  const admin = getStoredAdmin();
  const [tab, setTab] = useState("hearings");

  if (!admin) return <Navigate to="/admin/login" replace />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "1rem" }}>
        <h1>Curation Dashboard</h1>
        <div>
          {admin.displayName || admin.email} {admin.role && <span className="role-tag">{admin.role}</span>}{" "}
          <button
            className="btn btn-secondary"
            style={{ marginLeft: "0.75rem" }}
            onClick={() => {
              clearAdmin();
              window.location.href = "/admin/login";
            }}
          >
            Sign out
          </button>
        </div>
      </div>

      <div className="admin-shell">
        <nav className="admin-nav">
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </nav>
        <div>
          {tab === "hearings" && <HearingReviewQueue admin={admin} />}
          {tab === "news" && <NewsReviewQueue />}
          {tab === "community" && <CommunitySubmissionQueue admin={admin} />}
          {tab === "federal" && <AppellateSupplement admin={admin} />}
          {tab === "calendar" && <AcademicCalendar admin={admin} />}
          {tab === "activity" && <ActivityLog />}
        </div>
      </div>
    </div>
  );
}

// --- Hearings needing case-category or hearing-type review, plus blurb/exclusion editing ---

function HearingReviewQueue({ admin }) {
  const [hearings, setHearings] = useState(null);
  const [error, setError] = useState(null);
  const [drafts, setDrafts] = useState({});

  function load() {
    api.reviewQueueHearings().then(setHearings).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function saveDraft(id) {
    await api.draftBlurb(id, drafts[id] || "");
    load();
  }
  async function publish(id) {
    await api.publishBlurb(id);
    load();
  }
  async function exclude(id, isExcluded) {
    await api.setExclusion(id, isExcluded, isExcluded ? "Marked sensitive/not worth surfacing by an Editor" : null);
    load();
  }

  if (error) return <p className="message-error">{error}</p>;
  if (!hearings) return <p>Loading&hellip;</p>;

  return (
    <div>
      <h2>Hearings the pipeline couldn't confidently categorize</h2>
      <p className="disclaimer">
        Case-number prefix didn't match the decode table, or the hearing-type string is new/unusual.
        These still appear on the public site under "show all types" -- reviewing them here just helps
        you decide whether to add a blurb, exclude one, or (over time) teach the decoder to recognize
        the pattern.
      </p>
      {hearings.length === 0 && <p>Nothing in the queue right now.</p>}
      {hearings.map((h) => (
        <div className="card" key={h.id}>
          <h3>
            {h.case_number} &middot; {h.hearing_type_raw} &middot; {h.date} {h.time}
          </h3>
          <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
            Decoded category: <strong>{h.case_category}</strong> &middot; hearing-type bucket:{" "}
            <strong>{h.hearing_type_category}</strong>
          </p>
          <label>Draft "why watch this" blurb</label>
          <textarea
            defaultValue={h.curated_blurb || ""}
            onChange={(e) => setDrafts((d) => ({ ...d, [h.id]: e.target.value }))}
          />
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
            <button className="btn btn-secondary" onClick={() => saveDraft(h.id)}>
              Save draft
            </button>
            {admin.role === "editor" && (
              <>
                <button className="btn" onClick={() => publish(h.id)}>
                  Publish blurb
                </button>
                <button className="btn btn-danger" onClick={() => exclude(h.id, !h.is_excluded)}>
                  {h.is_excluded ? "Un-exclude" : "Exclude from public list"}
                </button>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// --- Unmatched news articles ---

function NewsReviewQueue() {
  const [mentions, setMentions] = useState(null);
  const [error, setError] = useState(null);
  const [hearingIdInput, setHearingIdInput] = useState({});

  function load() {
    api.reviewQueueNewsMentions().then(setMentions).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function link(id) {
    if (!hearingIdInput[id]) return;
    await api.linkNewsMention(id, hearingIdInput[id]);
    load();
  }
  async function discard(id) {
    await api.discardNewsMention(id);
    load();
  }

  if (error) return <p className="message-error">{error}</p>;
  if (!mentions) return <p>Loading&hellip;</p>;

  return (
    <div>
      <h2>News articles that couldn't be auto-matched to a hearing</h2>
      <p className="disclaimer">
        No case number was found in the article (common -- reporters don't always print one). Link it
        to the right hearing by pasting that hearing's ID, or discard it if it's not Boulder-court
        relevant.
      </p>
      {mentions.length === 0 && <p>Nothing in the queue right now.</p>}
      <table className="data-table">
        <thead>
          <tr>
            <th>Headline</th>
            <th>Source</th>
            <th>Link to hearing ID</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {mentions.map((m) => (
            <tr key={m.id}>
              <td>
                <a href={m.article_url} target="_blank" rel="noreferrer">
                  {m.headline}
                </a>
              </td>
              <td>{m.source_name}</td>
              <td>
                <input
                  placeholder="hearing UUID"
                  style={{ width: "100%" }}
                  onChange={(e) => setHearingIdInput((s) => ({ ...s, [m.id]: e.target.value }))}
                />
              </td>
              <td style={{ display: "flex", gap: "0.4rem" }}>
                <button className="btn btn-secondary" onClick={() => link(m.id)}>
                  Link
                </button>
                <button className="btn btn-danger" onClick={() => discard(m.id)}>
                  Discard
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Community submissions ("add details" from a public visitor) -----------

function CommunitySubmissionQueue({ admin }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  function load() {
    api.reviewQueueCommunitySubmissions().then(setItems).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function approve(id) {
    await api.approveCommunitySubmission(id);
    load();
  }
  async function reject(id) {
    await api.rejectCommunitySubmission(id);
    load();
  }

  if (error) return <p className="message-error">{error}</p>;
  if (!items) return <p>Loading&hellip;</p>;

  return (
    <div>
      <h2>Visitor-submitted case details</h2>
      <p className="disclaimer">
        Someone browsing the site added a summary or a judge's name for a hearing. Section 4's
        exclusion/judgment guardrails apply here the same as everywhere else -- approving publishes
        it (and sets the judge's name on the hearing); rejecting discards it.
      </p>
      {items.length === 0 && <p>Nothing in the queue right now.</p>}
      {items.map((s) => (
        <div className="card" key={s.id}>
          <h3>Case {s.hearing_case_number}</h3>
          {s.judge_name && <p><strong>Judge:</strong> {s.judge_name}</p>}
          {s.summary_text && <p className="blurb">{s.summary_text}</p>}
          {s.submitter_context && (
            <p style={{ fontSize: "0.82rem", color: "var(--ink-soft)" }}>
              Submitter context (not shown publicly): {s.submitter_context}
            </p>
          )}
          {admin.role === "editor" ? (
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn" onClick={() => approve(s.id)}>Approve</button>
              <button className="btn btn-danger" onClick={() => reject(s.id)}>Reject</button>
            </div>
          ) : (
            <p style={{ fontSize: "0.82rem", color: "var(--ink-soft)" }}>Only an Editor can approve or reject.</p>
          )}
        </div>
      ))}
    </div>
  );
}

// --- Federal supplement: search CourtListener, flag, publish ---

const COURT_PRESET_TO_LOCATION = {
  scotus: "us_supreme_court",
  colo: "colorado_supreme_court",
  coloctapp: "colorado_court_of_appeals",
};

function AppellateSupplement({ admin }) {
  const [courts, setCourts] = useState({});
  const [court, setCourt] = useState("colo");
  const [query, setQuery] = useState("Boulder");
  const [resultType, setResultType] = useState("o");
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [flagged, setFlagged] = useState([]);

  useEffect(() => {
    api.appellateCourtPresets().then(setCourts).catch(() => {});
  }, []);

  function loadFlagged() {
    api.listFlaggedAppellateCandidates().then(setFlagged).catch(() => {});
  }
  useEffect(loadFlagged, []);

  async function search() {
    setError(null);
    try {
      setResults(await api.searchAppellateCandidates(query, court, resultType));
    } catch (e) {
      setError(e.message);
    }
  }

  async function flag(candidate) {
    await api.flagAppellateCandidate(candidate);
    loadFlagged();
  }

  async function publish(candidate) {
    const date = prompt(
      "Hearing date (YYYY-MM-DD)? For Colorado's own appellate courts, check the real PDF oral-argument " +
      "calendar first (coloradojudicial.gov/supreme-court/supreme-court-oral-arguments or " +
      ".../topic/77/court-appeals-oral-arguments) -- CourtListener doesn't have a scheduling feed for them.",
      candidate.date_filed?.slice(0, 10) || ""
    );
    if (!date) return;
    await api.publishAppellateCandidate({
      case_name: candidate.case_name,
      docket_number: candidate.docket_number || candidate.absolute_url,
      court_location: COURT_PRESET_TO_LOCATION[court] || "us_district_colorado",
      court_note: candidate.court,
      date,
      hearing_type_raw: "Oral Argument",
      curated_blurb: `${candidate.case_name} (${candidate.court}). See ${candidate.absolute_url}`,
      source_url: candidate.absolute_url,
    });
    alert("Published to the public feed.");
  }

  return (
    <div>
      <h2>CourtListener search (Section 2.3 appellate supplement)</h2>
      <p className="disclaimer">
        Search federal courts or Colorado's own Supreme Court / Court of Appeals. A Contributor can
        flag a result for an Editor to review; only an Editor can publish one to the public feed.
        Deliberately manual -- relevance isn't a keyword filter, it's a judgment call, and neither
        CourtListener nor Colorado publishes a structured oral-argument schedule for its own
        appellate courts (only PDFs), so the actual date has to be confirmed by hand either way.
      </p>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        <select value={court} onChange={(e) => setCourt(e.target.value)}>
          {Object.entries(courts).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <input value={query} onChange={(e) => setQuery(e.target.value)} style={{ flex: 1, minWidth: "10rem" }} />
        <select value={resultType} onChange={(e) => setResultType(e.target.value)}>
          <option value="o">Opinions</option>
          <option value="oa">Oral argument audio</option>
        </select>
        <button className="btn" onClick={search}>
          Search
        </button>
      </div>
      {error && <p className="message-error">{error}</p>}
      {results && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Case</th>
              <th>Court</th>
              <th>Date</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {results.map((c) => (
              <tr key={c.absolute_url}>
                <td>
                  <a href={c.absolute_url} target="_blank" rel="noreferrer">
                    {c.case_name}
                  </a>
                  {c.already_in_news && <span className="badge badge-news" style={{ marginLeft: "0.5rem" }}>In the news</span>}
                </td>
                <td>{c.court}</td>
                <td>{c.date_filed}</td>
                <td style={{ display: "flex", gap: "0.4rem" }}>
                  <button className="btn btn-secondary" onClick={() => flag(c)}>
                    Flag for review
                  </button>
                  {admin.role === "editor" && (
                    <button className="btn" onClick={() => publish(c)}>
                      Publish
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 style={{ marginTop: "2rem" }}>Flagged for Editor review</h3>
      {flagged.length === 0 && <p>Nothing flagged yet.</p>}
      <ul>
        {flagged.map((f, i) => (
          <li key={i}>
            {f.candidate.case_name} -- flagged by {f.flagged_by}
            {f.candidate.already_in_news && <span className="badge badge-news" style={{ marginLeft: "0.5rem" }}>In the news</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- Academic calendar config ---

function AcademicCalendar({ admin }) {
  const [periods, setPeriods] = useState(null);
  const [label, setLabel] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [type, setType] = useState("break");
  const [error, setError] = useState(null);

  function load() {
    api.listAcademicCalendar().then(setPeriods).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function onSubmit(e) {
    e.preventDefault();
    try {
      await api.createAcademicCalendarPeriod({ label, start_date: startDate, end_date: endDate, type });
      setLabel("");
      setStartDate("");
      setEndDate("");
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <h2>Academic calendar periods</h2>
      <p className="disclaimer">
        Enter CU Boulder's break and finals weeks each term. The public site shows a de-emphasis
        banner (not a hidden view) during these windows, and the weekly digest shortens itself.
      </p>

      {admin.role === "editor" ? (
        <form className="form-grid" onSubmit={onSubmit} style={{ marginBottom: "1.5rem" }}>
          <div>
            <label>Label</label>
            <input required value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Spring Break 2027" />
          </div>
          <div>
            <label>Start date</label>
            <input required type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label>End date</label>
            <input required type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div>
            <label>Type</label>
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="break">Break</option>
              <option value="finals">Finals</option>
            </select>
          </div>
          <button className="btn" type="submit">
            Add period
          </button>
          {error && <p className="message-error">{error}</p>}
        </form>
      ) : (
        <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
          Only Editors can add academic-calendar periods; Contributors can view them here.
        </p>
      )}

      <table className="data-table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Start</th>
            <th>End</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody>
          {(periods || []).map((p) => (
            <tr key={p.id}>
              <td>{p.label}</td>
              <td>{p.start_date}</td>
              <td>{p.end_date}</td>
              <td style={{ textTransform: "capitalize" }}>{p.type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Activity log ---

function ActivityLog() {
  const [entries, setEntries] = useState(null);
  useEffect(() => {
    api.activityLog().then(setEntries).catch(() => setEntries([]));
  }, []);

  if (!entries) return <p>Loading&hellip;</p>;

  return (
    <div>
      <h2>Activity log</h2>
      <p className="disclaimer">So the team can see who's already touched what.</p>
      <table className="data-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>Action</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i}>
              <td>{new Date(e.at).toLocaleString()}</td>
              <td>{e.admin}</td>
              <td>{e.action}</td>
              <td>{e.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
