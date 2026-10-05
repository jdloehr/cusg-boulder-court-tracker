import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import { weekdayAbbr } from "../availabilityMatch.js";
import { TAG_COLOR_LEGEND } from "../hearingTagColors.js";
import HearingTypeTag from "./HearingTypeTag.jsx";
import { firstSentence } from "../textUtils.js";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MAX_DOTS_PER_DAY = 3;
// Calendar-view doc's "qualifier": past this many hearings in one day, a
// flat list is "just as overwhelming as the crowded grid was, only pushed
// one click deeper" -- switch the sidebar to a grouped summary instead.
const HIGH_VOLUME_THRESHOLD = 20;
const TAG_LABEL_BY_KEY = Object.fromEntries(TAG_COLOR_LEGEND.map((t) => [t.key, t.label]));

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function monthParamFor(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function parseMonthParam(value) {
  const m = /^(\d{4})-(\d{2})$/.exec(value || "");
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, 1);
}

function isoDate(year, month, day) {
  const d = new Date(year, month, day);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Calendar-view doc's "qualifier": the grid's job is to show *where*
// things are busy, not to be readable in full from one cell -- so the
// day cell holds no text at all, formatted sensibly so a heavy real
// docket day (Boulder arraignment/traffic sessions can run into the
// hundreds) doesn't need the badge to grow to fit it.
function formatOverflowCount(n) {
  return n > 99 ? "99+" : `+${n}`;
}

// Calendar-view doc, Feature 1: a month-grid view behind a List/Month
// toggle on the existing Calendar page (HearingList.jsx), not a separate
// route. Fetches only the viewed month's hearings, reusing the existing
// GET /api/hearings date_from/date_to params -- no new backend endpoint.
export default function MonthCalendar({ hearingTypeCategory, caseCategory, courtLocation }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const admin = getStoredAdmin();

  const viewedMonth = parseMonthParam(searchParams.get("month")) || new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  const year = viewedMonth.getFullYear();
  const month = viewedMonth.getMonth();

  const [hearings, setHearings] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState(todayISO());
  const [teamAvailability, setTeamAvailability] = useState(null);
  const [recommendedHearingIds, setRecommendedHearingIds] = useState(new Set());

  function goToMonth(date) {
    const params = new URLSearchParams(searchParams);
    params.set("month", monthParamFor(date));
    setSearchParams(params);
  }

  // Real bug caught manually: selectedDate never updated on Previous/Next
  // month (or a bookmarked ?month= link) -- it stayed pinned to whatever
  // day was selected before, which usually isn't even a cell in the newly
  // viewed month. The sidebar then showed a stale date with "Nothing
  // scheduled" and no cell in the grid was ever highlighted as selected.
  // Re-pick today if it's in the newly viewed month, else the 1st.
  useEffect(() => {
    const monthPrefix = `${year}-${String(month + 1).padStart(2, "0")}`;
    const todayIso = todayISO();
    setSelectedDate(todayIso.startsWith(monthPrefix) ? todayIso : isoDate(year, month, 1));
  }, [year, month]);

  useEffect(() => {
    // Real bug, reported live: with no loading state at all, an in-flight
    // fetch looked identical to a genuinely empty month -- especially
    // confusing on this host's free tier, where the very first request
    // after any idle period can take up to a minute to wake the backend
    // up, making the grid look broken rather than just loading.
    setError(null);
    setLoading(true);
    let ignore = false;
    const firstOfMonth = isoDate(year, month, 1);
    const lastOfMonth = isoDate(year, month + 1, 0);
    const params = { date_from: firstOfMonth, date_to: lastOfMonth, court_location: courtLocation || undefined };
    // Month view's whole point is seeing everything scheduled -- only
    // narrow to one type if the shared filter explicitly picked one
    // (not the List view's own narrower "" default).
    if (hearingTypeCategory && hearingTypeCategory !== "__all__") {
      params.hearing_type_category = hearingTypeCategory;
    } else {
      params.show_all_types = "true";
    }
    if (caseCategory) params.case_category = caseCategory;
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
  }, [year, month, hearingTypeCategory, caseCategory, courtLocation]);

  // Justice-only recurring weekly availability, fetched once -- the same
  // data TeamAvailability.jsx already uses. A calendar date's availability
  // profile is just whatever its weekday's recurring profile is (Justice
  // availability isn't tied to specific calendar dates), so no new
  // backend endpoint is needed for the per-day gauge below.
  useEffect(() => {
    if (!admin?.isJustice) return;
    api.teamAvailability().then(setTeamAvailability).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [admin?.isJustice]);

  // Calendar-view doc's "qualifier": the sidebar's "Notable" section on a
  // heavy day surfaces anything already flagged elsewhere (a Justice
  // recommendation) -- fetched once, same "small, rarely changes
  // mid-visit" reasoning Home.jsx/HearingList.jsx already use for this
  // exact call.
  useEffect(() => {
    api.listRecommendations().then((recs) => setRecommendedHearingIds(new Set(recs.map((r) => r.hearing_id)))).catch(() => {});
  }, []);

  const hearingsByDate = useMemo(() => {
    const map = new Map();
    for (const h of hearings || []) {
      if (!map.has(h.date)) map.set(h.date, []);
      map.get(h.date).push(h);
    }
    return map;
  }, [hearings]);

  // Six full weeks (42 days), including the leading/trailing days from
  // adjacent months -- those render grayed out with no dots, and
  // deliberately aren't fetched (the doc's own "refetch only this
  // month's data").
  const gridStart = new Date(year, month, 1);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay());
  const days = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return d;
  });

  return (
    <div>
      <div className="month-nav">
        <button className="btn btn-secondary" onClick={() => goToMonth(new Date(year, month - 1, 1))} aria-label="Previous month">
          &lsaquo;
        </button>
        <h2 className="month-nav-label">
          {viewedMonth.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
        </h2>
        <button className="btn btn-secondary" onClick={() => goToMonth(new Date(year, month + 1, 1))} aria-label="Next month">
          &rsaquo;
        </button>
        <button className="btn btn-secondary" onClick={() => goToMonth(new Date())}>
          Today
        </button>
      </div>

      {error && <p className="message-error">Couldn't load hearings: {error}</p>}

      {!error && hearings === null && (
        <p>
          Loading&hellip; (the first request of the day can take up to a minute while the server
          wakes up)
        </p>
      )}
      {!error && loading && hearings !== null && (
        <p style={{ color: "var(--ink-soft)", fontSize: "0.9rem" }}>Updating&hellip;</p>
      )}

      {!error && hearings !== null && <div className="month-calendar-layout">
        <div className="month-grid" role="grid" aria-label={viewedMonth.toLocaleDateString(undefined, { month: "long", year: "numeric" })}>
          {WEEKDAY_LABELS.map((label) => (
            <div className="month-grid-weekday" key={label}>{label}</div>
          ))}
          {days.map((d) => {
            const iso = isoDate(d.getFullYear(), d.getMonth(), d.getDate());
            const inMonth = d.getMonth() === month;
            const dayHearings = hearingsByDate.get(iso) || [];
            const isToday = iso === todayISO();
            const isSelected = iso === selectedDate;
            const overflow = dayHearings.length - MAX_DOTS_PER_DAY;
            return (
              <button
                type="button"
                key={iso}
                className={`month-grid-day ${inMonth ? "" : "outside-month"} ${isSelected ? "selected" : ""}`}
                onClick={() => setSelectedDate(iso)}
                aria-pressed={isSelected}
                aria-label={`${d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}${
                  dayHearings.length > 0 ? `, ${dayHearings.length} hearing${dayHearings.length === 1 ? "" : "s"}` : ""
                }`}
              >
                <span className={`month-grid-date ${isToday ? "today" : ""}`}>{d.getDate()}</span>
                {/* Qualifier: dots, not text chips -- the grid shows
                    *where* things are busy, the sidebar explains what.
                    Always dots regardless of count, never a mix. */}
                <span className="month-grid-dots">
                  {dayHearings.slice(0, MAX_DOTS_PER_DAY).map((h) => (
                    <HearingDot key={h.id} hearing={h} />
                  ))}
                  {overflow > 0 && <span className="month-grid-overflow">{formatOverflowCount(overflow)}</span>}
                </span>
              </button>
            );
          })}
        </div>

        <DaySidebar
          selectedDate={selectedDate}
          hearings={hearingsByDate.get(selectedDate) || []}
          isJustice={admin?.isJustice}
          teamAvailability={teamAvailability}
          recommendedHearingIds={recommendedHearingIds}
        />
      </div>}
    </div>
  );
}

// Qualifier: a small colored dot per hearing, no label text in the grid
// cell itself -- clicking still goes straight to that hearing (same as
// the chips it replaces), and a native `title` plus visible aria-label
// cover the "hover or tap... lightweight tooltip with the hearing title
// and time" ask without a custom tooltip-state machine (title shows on
// hover on desktop and on long-press on most mobile browsers).
function HearingDot({ hearing }) {
  const label = `${firstSentence(hearing.hearing_type_display)} – ${hearing.time || "time TBD"}`;
  return (
    <Link
      to={`/hearings/${hearing.id}`}
      className={`month-grid-dot tag-dot-${hearing.tag_color}`}
      title={label}
      aria-label={label}
      onClick={(e) => e.stopPropagation()}
    />
  );
}

function DaySidebar({ selectedDate, hearings, isJustice, teamAvailability, recommendedHearingIds }) {
  const [search, setSearch] = useState("");
  const dateLabel = new Date(`${selectedDate}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  });
  const isHighVolume = hearings.length > HIGH_VOLUME_THRESHOLD;

  return (
    <aside className="day-sidebar">
      <p className="day-sidebar-label">Selected Day</p>
      <h3 style={{ marginTop: 0 }}>{dateLabel}</h3>

      {hearings.length === 0 && <p style={{ color: "var(--ink-soft)", fontSize: "0.9rem" }}>Nothing scheduled.</p>}

      {isHighVolume ? (
        <HighVolumeDaySummary hearings={hearings} selectedDate={selectedDate} recommendedHearingIds={recommendedHearingIds}
                               search={search} onSearchChange={setSearch} />
      ) : (
        hearings.length > 0 && (
          <table className="schedule">
            <tbody>
              {hearings.map((h) => (
                <tr key={h.id}>
                  <td style={{ whiteSpace: "nowrap", color: "var(--ink-soft)", fontSize: "0.85rem" }}>{h.time || "TBD"}</td>
                  <td>
                    <HearingTypeTag label={firstSentence(h.hearing_type_display)} color={h.tag_color} hearingId={h.id} />
                  </td>
                  <td>
                    <a href={`/hearings/${h.id}`}>{h.case_number}</a>
                  </td>
                  <td style={{ color: "var(--ink-soft)", fontSize: "0.85rem" }}>
                    {h.courtroom ? `Courtroom ${h.courtroom}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}

      {hearings.length > 0 && (
        <p style={{ marginTop: "0.5rem" }}>
          <a href={`/hearings?view=list&date_from=${selectedDate}&date_to=${selectedDate}`}>
            View full day on the docket &rarr;
          </a>
        </p>
      )}

      {isJustice && <DayAvailabilityGauge selectedDate={selectedDate} teamAvailability={teamAvailability} />}

      <div className="day-sidebar-legend">
        <p className="day-sidebar-label">Hearing types</p>
        {TAG_COLOR_LEGEND.map((t) => (
          <span className="day-sidebar-legend-item" key={t.key}>
            <span className={`day-sidebar-legend-swatch tag-dot-${t.key}`} aria-hidden="true" />
            {t.label}
          </span>
        ))}
      </div>
    </aside>
  );
}

const SEARCH_RESULT_CAP = 15;

// Qualifier: past HIGH_VOLUME_THRESHOLD, a flat list "is just as
// overwhelming as the crowded grid was, only pushed one click deeper."
// Leads with grouped counts, surfaces anything already flagged
// elsewhere (Notable), and offers a search -- but deliberately never
// renders the full row-by-row list inline no matter how someone
// filters; that's what the List-view handoff link (in the parent) is
// for, where real pagination already makes sense.
function HighVolumeDaySummary({ hearings, recommendedHearingIds, search, onSearchChange }) {
  const counts = useMemo(() => {
    const byColor = new Map();
    for (const h of hearings) {
      byColor.set(h.tag_color, (byColor.get(h.tag_color) || 0) + 1);
    }
    return [...byColor.entries()].sort(([, a], [, b]) => b - a);
  }, [hearings]);

  const notable = useMemo(
    () => hearings.filter((h) => recommendedHearingIds.has(h.id) || h.news_mentions?.length > 0),
    [hearings, recommendedHearingIds]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return hearings.filter((h) =>
      h.case_number.toLowerCase().includes(q) ||
      (h.courtroom || "").toLowerCase().includes(q) ||
      h.hearing_type_display.toLowerCase().includes(q)
    );
  }, [hearings, search]);

  return (
    <div className="day-summary">
      <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
        {hearings.length} hearings scheduled -- too many to list here. Grouped by type below.
      </p>

      {notable.length > 0 && (
        <div className="day-summary-notable">
          <p className="day-sidebar-label">Notable</p>
          {notable.map((h) => (
            <p key={h.id} style={{ margin: "0.2rem 0" }}>
              <HearingTypeTag label={firstSentence(h.hearing_type_display)} color={h.tag_color} hearingId={h.id} />{" "}
              <a href={`/hearings/${h.id}`}>{h.case_number}</a>
              {recommendedHearingIds.has(h.id) && " ★"}
              {h.news_mentions?.length > 0 && " • in the news"}
            </p>
          ))}
        </div>
      )}

      <p className="day-sidebar-label" style={{ marginTop: "0.75rem" }}>By type</p>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {counts.map(([color, count]) => (
          <li key={color} style={{ display: "flex", alignItems: "center", gap: "0.4rem", margin: "0.15rem 0", fontSize: "0.88rem" }}>
            <span className={`day-sidebar-legend-swatch tag-dot-${color}`} aria-hidden="true" />
            {count} {TAG_LABEL_BY_KEY[color] || color}
          </li>
        ))}
      </ul>

      <label style={{ display: "block", marginTop: "0.75rem" }}>
        <span className="day-sidebar-label">Find a specific case</span>
        <input
          type="search"
          placeholder="Case number, courtroom, or hearing type"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          style={{ width: "100%" }}
        />
      </label>
      {search.trim() && (
        <div style={{ marginTop: "0.5rem" }}>
          {filtered.slice(0, SEARCH_RESULT_CAP).map((h) => (
            <p key={h.id} style={{ margin: "0.2rem 0", fontSize: "0.88rem" }}>
              <HearingTypeTag label={firstSentence(h.hearing_type_display)} color={h.tag_color} hearingId={h.id} />{" "}
              <a href={`/hearings/${h.id}`}>{h.case_number}</a>
              {h.courtroom ? ` · Courtroom ${h.courtroom}` : ""}
            </p>
          ))}
          {filtered.length === 0 && <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>No matches.</p>}
          {filtered.length > SEARCH_RESULT_CAP && (
            <p style={{ fontSize: "0.82rem", color: "var(--ink-soft)" }}>
              {filtered.length - SEARCH_RESULT_CAP} more match -- use "View full day on the docket" below for the full list.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// Calendar-view doc: "3 of 5 Justices free this day" plus a red-to-green
// bar with a marker -- Justice-only (hidden entirely, not grayed out, for
// anyone else, matching how the per-hearing meter elsewhere is completely
// absent for non-Justices). Justice availability is recurring weekly, not
// tied to a specific calendar date, so a day's profile is just whatever
// its weekday's precomputed cells already say (same data
// TeamAvailability.jsx renders as a full heatmap) -- averaged across that
// weekday's slots, per the chosen "average across the day's slots" design.
function DayAvailabilityGauge({ selectedDate, teamAvailability }) {
  if (!teamAvailability) return null;

  const weekday = weekdayAbbr(new Date(`${selectedDate}T00:00:00`));
  const cellsForDay = teamAvailability.cells.filter((c) => c.day_of_week === weekday);
  const total = teamAvailability.total_justices;

  if (cellsForDay.length === 0 || total === 0) {
    return (
      <div className="day-availability-gauge">
        <p style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>No availability data for this day.</p>
      </div>
    );
  }

  const avgFree = cellsForDay.reduce((sum, c) => sum + c.free_count, 0) / cellsForDay.length;
  const ratio = avgFree / total;
  const hue = Math.round(ratio * 120); // same red(0)-to-green(120) sweep as AvailabilityMeter.jsx

  return (
    <div className="day-availability-gauge">
      <p style={{ fontSize: "0.85rem", margin: "0 0 0.4rem" }}>
        {Math.round(avgFree)} of {total} Justices free this day (averaged across the day)
      </p>
      <div className="day-availability-gauge-bar">
        <span className="day-availability-gauge-marker" style={{ left: `${ratio * 100}%`, background: `hsl(${hue}, 70%, 35%)` }} />
      </div>
    </div>
  );
}
