// Court Passport redesign: the circular courthouse mark used in the nav
// and footer -- navy disc, dashed gold ring, cream columns (or the
// inverse on a dark surface). Hand-authored inline SVG, same convention
// as ColonnadeMotif.jsx. Paths copied directly from the mockups.
export default function CourtPassportMark({ size = 40, dark = false, ...props }) {
  const discColor = dark ? "#FAF8F3" : "#1B2A38";
  const columnColor = dark ? "#1B2A38" : "#FAF8F3";
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" {...props}>
      <circle cx="20" cy="20" r="18.5" fill={discColor} />
      <circle cx="20" cy="20" r="15.5" fill="none" stroke="#C29541" strokeWidth="1" strokeDasharray="2 2" />
      <path d="M10 15.5L20 9.5l10 6z" fill={columnColor} />
      <rect x="11.3" y="17" width="2.8" height="9" fill={columnColor} />
      <rect x="16.1" y="17" width="2.8" height="9" fill={columnColor} />
      <rect x="21.1" y="17" width="2.8" height="9" fill={columnColor} />
      <rect x="25.9" y="17" width="2.8" height="9" fill={columnColor} />
      <rect x="9.5" y="27" width="21" height="2.2" fill={columnColor} />
    </svg>
  );
}
