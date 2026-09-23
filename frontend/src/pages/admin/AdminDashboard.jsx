import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, clearAdmin, getStoredAdmin } from "../../api.js";

const TABS = [
  { key: "hearings", label: "Review Queue: Hearings" },
  { key: "news", label: "Review Queue: News" },
  { key: "community", label: "Review Queue: Community" },
  { key: "reports", label: "Reports" },
  { key: "federal", label: "Appellate Supplement" },
  { key: "calendar", label: "Academic Calendar" },
  { key: "justices", label: "Justice Accounts" },
  { key: "security", label: "Account Security" },
  { key: "activity", label: "Activity Log" },
];

export default function AdminDashboard() {
  const admin = getStoredAdmin();
  const [tab, setTab] = useState("hearings");
  // Phase-6 doc, Section 4: "surface a visible count ... so it isn't easy
  // to forget about" -- fetched once on mount, independent of which tab
  // is selected, so the badge shows up even before a curator ever opens
  // the News tab. Refreshed via onCountChange whenever that tab's own
  // actions (confirm/reject/link/discard) change the queue.
  const [newsQueueCount, setNewsQueueCount] = useState(null);
  useEffect(() => {
    api.reviewQueueNewsMentionsCount().then((r) => setNewsQueueCount(r.count)).catch(() => {});
  }, []);

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
              {t.key === "news" && !!newsQueueCount && (
                <span className="queue-count-badge">{newsQueueCount}</span>
              )}
            </button>
          ))}
        </nav>
        <div>
          {tab === "hearings" && <HearingReviewQueue admin={admin} />}
          {tab === "news" && <NewsReviewQueue admin={admin} onCountChange={setNewsQueueCount} />}
          {tab === "community" && <CommunitySubmissionQueue admin={admin} />}
          {tab === "federal" && <AppellateSupplement admin={admin} />}
          {tab === "calendar" && <AcademicCalendar admin={admin} />}
          {tab === "reports" && <ReportsQueue />}
          {tab === "justices" && <JusticeInvites admin={admin} />}
          {tab === "security" && <TwoFactorSettings />}
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

// --- News articles awaiting a match decision (Phase-6 doc, Section 4) ------
// Two real states now, not one: a *suggested* match (the algorithm found
// a real candidate, just not confidently enough to auto-attach -- one
// click to confirm or reject) and the original no-candidate-at-all
// unmatched_review (link by case number, or discard).

function NewsReviewQueue({ admin, onCountChange }) {
  const [mentions, setMentions] = useState(null);
  const [error, setError] = useState(null);
  const [caseNumberInput, setCaseNumberInput] = useState({});
  const [linkError, setLinkError] = useState({});
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [backfillResult, setBackfillResult] = useState(null);

  function load() {
    api.reviewQueueNewsMentions().then((data) => {
      setMentions(data);
      onCountChange?.(data.length);
    }).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function confirm(id) {
    await api.confirmSuggestedNewsMention(id);
    load();
  }
  async function reject(id) {
    await api.rejectSuggestedNewsMention(id);
    load();
  }
  async function linkByCaseNumber(id) {
    const caseNumber = caseNumberInput[id]?.trim();
    if (!caseNumber) return;
    setLinkError((s) => ({ ...s, [id]: null }));
    try {
      await api.linkNewsMention(id, { case_number: caseNumber });
      load();
    } catch (err) {
      setLinkError((s) => ({ ...s, [id]: err.message }));
    }
  }
  async function discard(id) {
    await api.discardNewsMention(id);
    load();
  }
  async function backfillRematch() {
    setBackfillBusy(true);
    setBackfillResult(null);
    try {
      const result = await api.backfillRematchNewsMentions();
      setBackfillResult(result);
      load();
    } finally {
      setBackfillBusy(false);
    }
  }

  if (error) return <p className="message-error">{error}</p>;
  if (!mentions) return <p>Loading&hellip;</p>;

  const suggested = mentions.filter((m) => m.match_status === "suggested_pending_review");
  const unmatched = mentions.filter((m) => m.match_status !== "suggested_pending_review");

  return (
    <div>
      <h2>News review queue</h2>
      <p className="disclaimer">
        Articles that publish automatically only when a case number is found, or a strong name +
        date match agrees -- everything else lands here for a quick human decision. Articles with no
        case number, no name candidate, and no court-relevant language at all are discarded
        automatically and never reach this queue.
      </p>
      {admin?.role === "editor" && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <p style={{ fontSize: "0.85rem" }}>
            Re-checks every item below against the current matching logic -- useful after a change to
            that logic, or to clear out older items (like this queue's original backlog) that predate
            an improvement.
          </p>
          <button className="btn btn-secondary" onClick={backfillRematch} disabled={backfillBusy}>
            {backfillBusy ? "Re-evaluating…" : "Re-evaluate all under current matching logic"}
          </button>
          {backfillResult && (
            <p className="message-success" style={{ marginTop: "0.5rem" }}>
              Checked {backfillResult.checked} -- discarded {backfillResult.discarded}, promoted to
              suggested {backfillResult.promoted_to_suggested}, auto-matched{" "}
              {backfillResult.promoted_to_auto_matched}, unchanged {backfillResult.unchanged}.
            </p>
          )}
        </div>
      )}

      {mentions.length === 0 && <p>Nothing in the queue right now.</p>}

      {suggested.length > 0 && (
        <>
          <h3>Suggested matches</h3>
          {suggested.map((m) => (
            <div className="card" key={m.id}>
              <h4 style={{ marginBottom: "0.3rem" }}>
                <a href={m.article_url} target="_blank" rel="noreferrer">{m.headline}</a>
              </h4>
              <p style={{ fontSize: "0.82rem", color: "var(--ink-soft)" }}>
                {m.source_name}
                {m.match_confidence && ` · ${m.match_confidence} confidence`}
                {m.extracted_party_candidates.length > 0 &&
                  ` · candidate name(s): ${m.extracted_party_candidates.join(", ")}`}
              </p>
              {m.suggested_hearing && (
                <p className="blurb">
                  Suggested: <strong>{m.suggested_hearing.case_number}</strong> -- {m.suggested_hearing.hearing_type_display}
                  {" "}({m.suggested_hearing.date}), parties: {m.suggested_hearing.party_names.join(", ")}
                </p>
              )}
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button className="btn" onClick={() => confirm(m.id)}>Confirm match</button>
                <button className="btn btn-secondary" onClick={() => reject(m.id)}>Reject</button>
              </div>
            </div>
          ))}
        </>
      )}

      {unmatched.length > 0 && (
        <>
          <h3 style={{ marginTop: suggested.length > 0 ? "1.5rem" : 0 }}>No candidate found</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Headline</th>
                <th>Source</th>
                <th>Link by case number</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {unmatched.map((m) => (
                <tr key={m.id}>
                  <td>
                    <a href={m.article_url} target="_blank" rel="noreferrer">{m.headline}</a>
                  </td>
                  <td>{m.source_name}</td>
                  <td>
                    <input
                      placeholder="e.g. 2026CR001452"
                      style={{ width: "100%" }}
                      onChange={(e) => setCaseNumberInput((s) => ({ ...s, [m.id]: e.target.value }))}
                    />
                    {linkError[m.id] && <p className="message-error" style={{ fontSize: "0.78rem" }}>{linkError[m.id]}</p>}
                  </td>
                  <td style={{ display: "flex", gap: "0.4rem" }}>
                    <button className="btn btn-secondary" onClick={() => linkByCaseNumber(m.id)}>
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
        </>
      )}
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
    const caseCategory = prompt(
      "Case category? (criminal, misdemeanor, traffic, civil, domestic_relations, probate, other) " +
      "-- CourtListener doesn't reliably expose this, so it's your call.",
      "civil"
    );
    if (!caseCategory) return;
    await api.publishAppellateCandidate({
      case_name: candidate.case_name,
      docket_number: candidate.docket_number || candidate.absolute_url,
      court_location: COURT_PRESET_TO_LOCATION[court] || "us_district_colorado",
      court_note: candidate.court,
      date,
      hearing_type_raw: "Oral Argument",
      case_category: caseCategory,
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

// --- Phase-3 doc, Section 1: invite-link Justice provisioning ---

function JusticeInvites({ admin }) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [title, setTitle] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const invite = await api.createInvite({ email, display_name: displayName, title: title || undefined });
      setResult(invite);
      setEmail("");
      setDisplayName("");
      setTitle("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (admin.role !== "editor") {
    return (
      <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
        Only an Editor (which every Justice account also is -- see Sign in) can invite a new Justice.
      </p>
    );
  }

  return (
    <div>
      <h2>Invite a Justice</h2>
      <p className="disclaimer">
        Not open self-registration -- only the 7-8 real CUSG Justices should ever have accounts.
        Enter their real name and email; they'll get a one-time link (expires in 48 hours) to set
        their own password and fill out their public profile. Signing in as a Justice also grants
        full curation-tool access.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="inviteEmail">Email</label>
          <input id="inviteEmail" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="inviteName">Name</label>
          <input id="inviteName" required value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="inviteTitle">Title (optional)</label>
          <input id="inviteTitle" placeholder="Chief Justice" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Creating…" : "Create invite"}
        </button>
        {error && <p className="message-error">{error}</p>}
      </form>

      {result && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <p className="message-success">
            Invite created for {result.display_name} ({result.email}). An email was queued (see the
            backend's email log if real delivery isn't set up yet) -- or share this link directly:
          </p>
          <input readOnly value={result.invite_link} onFocus={(e) => e.target.select()} style={{ width: "100%" }} />
          <p style={{ fontSize: "0.8rem", color: "var(--ink-soft)", marginTop: "0.4rem" }}>
            Expires {new Date(result.expires_at).toLocaleString()}. One-time use.
          </p>
        </div>
      )}

      <hr style={{ margin: "2rem 0" }} />

      <JusticeAllowlist />
    </div>
  );
}

// Lets a Justice request their own signup link (added on request, once
// "someone else has to invite me before I can invite myself" turned out
// to be a real bootstrapping annoyance) -- an Editor still has to add
// the email here first; that's the actual gate. Complements "Invite a
// Justice" above rather than replacing it.
function JusticeAllowlist() {
  const [entries, setEntries] = useState(null);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function load() {
    api.listAllowlist().then(setEntries).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addToAllowlist({ email, display_name: displayName, title: title || undefined });
      setEmail("");
      setDisplayName("");
      setTitle("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id) {
    await api.removeFromAllowlist(id);
    load();
  }

  return (
    <div>
      <h2>Self-service allow-list</h2>
      <p className="disclaimer">
        Add a Justice here once, and they can get their own signup link anytime from{" "}
        <Link to="/request-invite">Request your signup link</Link> by entering this exact email --
        no one else has to click "Create invite" for them. An unlisted email gets no link at all.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="allowlistEmail">Email</label>
          <input id="allowlistEmail" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="allowlistName">Name</label>
          <input id="allowlistName" required value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="allowlistTitle">Title (optional)</label>
          <input id="allowlistTitle" placeholder="Chief Justice" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <button className="btn btn-secondary" type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add to allow-list"}
        </button>
        {error && <p className="message-error">{error}</p>}
      </form>

      {entries && entries.length > 0 && (
        <table className="data-table" style={{ marginTop: "1rem" }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>{e.title ? `${e.title} ${e.display_name}` : e.display_name}</td>
                <td>{e.email}</td>
                <td>
                  <button className="btn btn-danger" onClick={() => remove(e.id)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// --- Phase-4 doc, Section 2.5: "Report" flagging queue ---

const REPORT_TARGET_LABELS = { archive_entry: "Archive entry", recommendation: "Recommendation" };

function ReportsQueue() {
  const [reports, setReports] = useState(null);
  const [showResolved, setShowResolved] = useState(false);

  function load() {
    api.listReports(showResolved).then(setReports).catch(() => setReports([]));
  }
  useEffect(load, [showResolved]);

  async function resolve(id) {
    await api.resolveReport(id);
    load();
  }

  if (!reports) return <p>Loading&hellip;</p>;

  return (
    <div>
      <h2>Reported content</h2>
      <p className="disclaimer">
        Flagged by a visitor via the "Report" link on the Archive or the recommendations board. This
        doesn't remove or hide anything by itself -- use the existing edit/delete tools on{" "}
        <Link to="/archive">Archive</Link> or <Link to="/recommendations">Court Recommendations</Link>{" "}
        if action is needed, then mark it resolved here.
      </p>
      <label style={{ fontSize: "0.85rem" }}>
        <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />{" "}
        Show resolved
      </label>
      {reports.length === 0 && <p>Nothing {showResolved ? "resolved" : "open"} right now.</p>}
      {reports.map((r) => (
        <div className="card" key={r.id}>
          <h3>{REPORT_TARGET_LABELS[r.target_type] || r.target_type}</h3>
          <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
            Reported {new Date(r.created_at).toLocaleString()}
            {r.target_url && (
              <>
                {" "}&middot; <Link to={r.target_url}>view on the site</Link>
              </>
            )}
          </p>
          <p className="blurb">"{r.target_summary}"</p>
          {r.reason && <p><strong>Reason given:</strong> {r.reason}</p>}
          {!r.resolved && (
            <button className="btn btn-secondary" onClick={() => resolve(r.id)}>
              Mark resolved
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

// --- Phase-4 doc, Section 2.3: two-factor authentication ---

function TwoFactorSettings() {
  const [status, setStatus] = useState(null); // "off" | "setting-up" | "on"
  const [setupData, setSetupData] = useState(null);
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState(null);
  const [disablePassword, setDisablePassword] = useState("");
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function startSetup() {
    setError(null);
    setBusy(true);
    try {
      const data = await api.setup2fa();
      setSetupData(data);
      setStatus("setting-up");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmSetup(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.confirm2fa(code);
      setBackupCodes(res.backup_codes);
      setStatus("on");
      setCode("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function disable(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.disable2fa(disablePassword);
      setStatus("off");
      setSetupData(null);
      setBackupCodes(null);
      setDisablePassword("");
      setMessage("Two-factor authentication turned off.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>Two-factor authentication</h2>
      <p className="disclaimer">
        Recommended for every account, Justice or curation-only -- Justice accounts in particular
        control public recommendations, attendance records, and public profiles. Uses any standard
        authenticator app (Google Authenticator, Authy, 1Password, etc.).
      </p>

      {message && <p className="message-success">{message}</p>}
      {error && <p className="message-error">{error}</p>}

      {backupCodes ? (
        <div className="card">
          <h3>Two-factor authentication is on</h3>
          <p>
            Save these backup codes somewhere safe -- each works once, and they're the only way back
            into your account if you lose your authenticator. <strong>They won't be shown again.</strong>
          </p>
          <pre style={{ background: "var(--paper)", padding: "0.75rem", fontSize: "0.95rem" }}>
            {backupCodes.join("\n")}
          </pre>
        </div>
      ) : status === "setting-up" && setupData ? (
        <div className="card">
          <h3>Scan this code</h3>
          <p>Scan with your authenticator app, or enter the key manually, then enter the 6-digit code it shows.</p>
          <img src={setupData.qr_code_data_uri} alt="2FA setup QR code" style={{ display: "block", margin: "0.75rem 0" }} />
          <p style={{ fontFamily: "monospace", fontSize: "0.9rem" }}>{setupData.secret}</p>
          <form className="form-grid" onSubmit={confirmSetup}>
            <div>
              <label htmlFor="totpConfirmCode">6-digit code</label>
              <input id="totpConfirmCode" required value={code} onChange={(e) => setCode(e.target.value)} />
            </div>
            <button className="btn" type="submit" disabled={busy}>
              {busy ? "Verifying…" : "Verify & turn on"}
            </button>
          </form>
        </div>
      ) : (
        <div>
          <button className="btn" onClick={startSetup} disabled={busy}>
            {busy ? "Starting…" : "Set up two-factor authentication"}
          </button>
          <details style={{ marginTop: "1rem" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.85rem", color: "var(--ink-soft)" }}>
              Already have it on and want to turn it off?
            </summary>
            <form className="form-grid" onSubmit={disable} style={{ marginTop: "0.75rem" }}>
              <div>
                <label htmlFor="disablePw">Current password</label>
                <input id="disablePw" type="password" required value={disablePassword}
                       onChange={(e) => setDisablePassword(e.target.value)} />
              </div>
              <button className="btn btn-danger" type="submit" disabled={busy}>
                Turn off two-factor authentication
              </button>
            </form>
          </details>
        </div>
      )}
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
