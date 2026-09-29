import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import { weekdayAbbr } from "../availabilityMatch.js";
import { TAG_COLOR_LEGEND } from "../hearingTagColors.js";
import HearingTypeTag from "./HearingTypeTag.jsx";
import { firstSentence } from "../textUtils.js";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MAX_CHIPS_PER_DAY = 3;

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
  const [selectedDate, setSelectedDate] = useState(todayISO());
  const [teamAvailability, setTeamAvailability] = useState(null);

  function goToMonth(date) {
    const params = new URLSearchParams(searchParams);
    params.set("month", monthParamFor(date));
    setSearchParams(params);
  }

  useEffect(() => {
    setError(null);
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

  const hearingsByDate = useMemo(() => {
    const map = new Map();
    for (const h of hearings || []) {
      if (!map.has(h.date)) map.set(h.date, []);
      map.get(h.date).push(h);
    }
    return map;
  }, [hearings]);

  // Six full weeks (42 days), including the leading/trailing days from
  // adjacent months -- those render grayed out with no chips, and
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

      <div className="month-calendar-layout">
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
            return (
              <button
                type="button"
                key={iso}
                className={`month-grid-day ${inMonth ? "" : "outside-month"} ${isSelected ? "selected" : ""}`}
                onClick={() => setSelectedDate(iso)}
                aria-pressed={isSelected}
                aria-label={d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
              >
                <span className={`month-grid-date ${isToday ? "today" : ""}`}>{d.getDate()}</span>
                <span className="month-grid-chips">
                  {dayHearings.slice(0, MAX_CHIPS_PER_DAY).map((h) => (
                    <HearingTypeTag
                      key={h.id}
                      label={firstSentence(h.hearing_type_display)}
                      color={h.tag_color}
                      hearingId={h.id}
                    />
                  ))}
                  {dayHearings.length > MAX_CHIPS_PER_DAY && (
                    <span className="month-grid-more">+{dayHearings.length - MAX_CHIPS_PER_DAY} more</span>
                  )}
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
        />
      </div>
    </div>
  );
}

function DaySidebar({ selectedDate, hearings, isJustice, teamAvailability }) {
  const dateLabel = new Date(`${selectedDate}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  });

  return (
    <aside className="day-sidebar">
      <p className="day-sidebar-label">Selected Day</p>
      <h3 style={{ marginTop: 0 }}>{dateLabel}</h3>

      {hearings.length === 0 && <p style={{ color: "var(--ink-soft)", fontSize: "0.9rem" }}>Nothing scheduled.</p>}
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
            <span className={`day-sidebar-legend-swatch tag-${t.key}`} aria-hidden="true" />
            {t.label}
          </span>
        ))}
      </div>
    </aside>
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
