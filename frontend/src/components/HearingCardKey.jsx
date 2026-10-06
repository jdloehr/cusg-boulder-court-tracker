import { getStoredAdmin } from "../api.js";

// Explains the marks that can show up on a hearing card below -- added
// on request after a Justice asked what the availability meter bar
// actually meant. Shows only the indicators the current viewer can
// actually see: the meter explanation is omitted entirely for anyone
// who isn't signed in as a Justice, since the meter itself never
// renders for them either.
export default function HearingCardKey() {
  const admin = getStoredAdmin();
  return (
    <div className="hearing-card-key">
      <span className="hearing-card-key-item">
        <span className="badge badge-news">&#9733; Recommended</span>
        <span>a Justice flagged this hearing</span>
      </span>
      <span className="hearing-card-key-item">
        <span className="badge badge-fits-schedule">&#10003; Fits your schedule</span>
        <span>matches your own saved free time</span>
      </span>
      {/* Oct 2026 review, Phase 4 item 7: the "Learn about this" badge
          itself was removed from every row (the detail page already
          links to its matching Learn topic), so this legend entry no
          longer explains anything a visitor can actually see here. */}
      <span className="hearing-card-key-item">
        <span className="badge badge-teaching-note">Justice's Note</span>
        <span>a Justice wrote something about this exact case</span>
      </span>
      {admin?.isJustice && (
        <span className="hearing-card-key-item">
          <span className="hearing-card-key-meter-swatch" aria-hidden="true" />
          <span>how many Justices are free then &mdash; click it to see who</span>
        </span>
      )}
    </div>
  );
}
