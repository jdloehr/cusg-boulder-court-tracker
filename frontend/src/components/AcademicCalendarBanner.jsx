import { useEffect, useState } from "react";
import { api } from "../api.js";

/** Section 5.5: de-emphasize, don't hide, content during CU breaks/finals. */
export default function AcademicCalendarBanner() {
  const [period, setPeriod] = useState(undefined); // undefined = loading, null = none

  useEffect(() => {
    api
      .academicCalendarCurrent()
      .then(setPeriod)
      .catch(() => setPeriod(null));
  }, []);

  if (!period) return null;

  const noun = period.type === "finals" ? "finals" : "break";
  return (
    <div className="banner" role="status">
      <strong>CU is on {noun} this week</strong> ({period.label}) -- here's what's on the docket if
      you're still around. Court proceedings don't pause for the academic calendar, so hearings below
      are still real and still worth knowing about.
    </div>
  );
}
