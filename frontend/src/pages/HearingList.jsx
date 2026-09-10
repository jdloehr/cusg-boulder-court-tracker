import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import AcademicCalendarBanner from "../components/AcademicCalendarBanner.jsx";
import { COURT_LOCATION_LABELS, COURT_LOCATION_TAG } from "../courtInfo.js";

const HORIZONS = [
  { label: "Next 2 weeks", days: 14 },
  { label: "Next month", days: 30 },
  { label: "This semester", days: 120 },
];

const CASE_CATEGORY_LABELS = {
  criminal: "Criminal (felony)",
  misdemeanor: "Misdemeanor",
  traffic: "Traffic",
  civil: "Civil",
  domestic_relations: "Domestic Relations",
  probate: "Probate",
  juvenile: "Juvenile",
  other: "Other",
};

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
function addDaysISO(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function HearingList() {
  const [hearingTypeCategory, setHearingTypeCategory] = useState("");
  const [hasNews, setHasNews] = useState(false);
  const [caseCategory, setCaseCategory] = useState("");
  const [courtLocation, setCourtLocation] = useState("");
  const [horizonDays, setHorizonDays] = useState(14);
  const [hearings, setHearings] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setError(null);
    setLoading(true);
    // `ignore` guards against a real race: the backend's free hosting
    // tier cold-starts in 30-60s when idle, so the *first* request (e.g.
    // on initial page load) can still be in flight when a filter change
    // fires a second, faster request. Without this guard, whichever
    // response happens to arrive *last* wins and overwrites the other --
    // in practice, the slow first request's stale (default-filter) result
    // would land after the fast one and silently undo the filter change,
    // which looks exactly like "the search doesn't refresh."
    let ignore = false;

    const params = {
      date_from: todayISO(),
      date_to: addDaysISO(horizonDays),
      case_category: caseCategory || undefined,
      court_location: courtLocation || undefined,
    };
    // "" (default option) -> let the backend apply Section 5.1's default
    // filter (jury trial/oral argument, in-person, or has a news mention).
    // "__all__" -> explicitly bypass that filter. Anything else -> a
    // specific hearing_type_category.
    if (hearingTypeCategory === "__all__") {
      params.show_all_types = "true";
    } else if (hearingTypeCategory) {
      params.hearing_type_category = hearingTypeCategory;
    }
    api
      .listHearings(params)
      .then((data) => {
        if (!ignore) setHearings(data);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [hearingTypeCategory, caseCategory, courtLocation, horizonDays]);

  const filtered = useMemo(() => {
    if (!hearings) return null;
    return hasNews ? hearings.filter((h) => h.news_mentions?.length > 0) : hearings;
  }, [hearings, hasNews]);

  const grouped = useMemo(() => {
    if (!filtered) return [];
    const byDate = new Map();
    for (const h of filtered) {
      if (!byDate.has(h.date)) byDate.set(h.date, []);
      byDate.get(h.date).push(h);
    }
    return [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  return (
    <>
      <h1>Upcoming Hearings</h1>
      <p className="disclaimer">
        Jury trials and oral arguments/motions hearings in Boulder-area courts, in person, worth
        sitting in on -- plus anything getting real local news coverage. Details can change; confirm
        before you go.
      </p>

      <AcademicCalendarBanner />

      <div className="filter-bar">
        <div className="filter-field">
          <label htmlFor="f-type">Hearing type</label>
          <select id="f-type" value={hearingTypeCategory} onChange={(e) => setHearingTypeCategory(e.target.value)}>
            <option value="">Jury trial + oral argument/motions (default)</option>
            <option value="jury_trial">Jury trial only</option>
            <option value="oral_argument_motions">Oral argument / motions only</option>
            <option value="__all__">Show all types</option>
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="f-case">Case category</label>
          <select id="f-case" value={caseCategory} onChange={(e) => setCaseCategory(e.target.value)}>
            <option value="">All</option>
            {Object.entries(CASE_CATEGORY_LABELS)
              .filter(([k]) => k !== "juvenile")
              .map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="f-court">Court</label>
          <select id="f-court" value={courtLocation} onChange={(e) => setCourtLocation(e.target.value)}>
            <option value="">All Boulder-area + federal</option>
            {Object.entries(COURT_LOCATION_LABELS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="f-horizon">Planning window</label>
          <select id="f-horizon" value={horizonDays} onChange={(e) => setHorizonDays(Number(e.target.value))}>
            {HORIZONS.map((h) => (
              <option key={h.days} value={h.days}>
                {h.label}
              </option>
            ))}
          </select>
        </div>
        <label className="filter-checkbox">
          <input type="checkbox" checked={hasNews} onChange={(e) => setHasNews(e.target.checked)} />
          In the news only
        </label>
      </div>

      {error && <p className="message-error">Couldn't load hearings: {error}</p>}

      {!error && filtered === null && (
        <p>
          Loading&hellip; (the first request of the day can take up to a minute while the server
          wakes up)
        </p>
      )}
      {!error && loading && filtered !== null && (
        <p style={{ color: "var(--ink-soft)", fontSize: "0.9rem" }}>Updating&hellip;</p>
      )}

      {!loading && filtered && filtered.length === 0 && (
        <div className="empty-state">
          <p>No hearings match these filters in this window. Try widening the planning window or clearing a filter.</p>
        </div>
      )}

      {grouped.map(([date, dayHearings]) => (
        <section key={date}>
          <h2 className="date-group-heading">
            {new Date(date + "T00:00:00").toLocaleDateString(undefined, {
              weekday: "long",
              month: "long",
              day: "numeric",
            })}
          </h2>
          {dayHearings.map((h) => (
            <HearingRow key={h.id} hearing={h} />
          ))}
        </section>
      ))}
    </>
  );
}

function HearingRow({ hearing }) {
  const hasNews = hearing.news_mentions?.length > 0;
  return (
    <Link to={`/hearings/${hearing.id}`} className="hearing-row">
      <div className="time">{hearing.time || "Time TBD"}</div>
      <div className="main">
        <div className="type">{firstSentence(hearing.hearing_type_display)}</div>
        <div className="meta">
          {CASE_CATEGORY_LABELS[hearing.case_category] || hearing.case_category} &middot; Case{" "}
          {hearing.case_number} &middot; {COURT_LOCATION_LABELS[hearing.court_location] || hearing.court_location}
          {hearing.courtroom ? ` — Courtroom ${hearing.courtroom}` : ""}
        </div>
      </div>
      <div className="badges">
        {hearing.court_location !== "boulder_county" && (
          <span className="badge badge-federal">{COURT_LOCATION_TAG[hearing.court_location] || hearing.court_location}</span>
        )}
        {hasNews && <span className="badge badge-news">In the news</span>}
        {hearing.status === "changed" && <span className="badge badge-changed">Time/place changed</span>}
        {hearing.status === "cancelled" && <span className="badge badge-cancelled">Cancelled</span>}
      </div>
    </Link>
  );
}

function firstSentence(text) {
  if (!text) return "";
  const idx = text.indexOf(": ");
  return idx > -1 ? text.slice(0, idx) : text.split(". ")[0];
}
