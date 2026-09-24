// Phase-6.2 doc, Section 3: "a subtle, low-opacity line-art colonnade
// motif in the background of the hero section (decorative only, behind
// the content)." Hand-authored inline SVG -- this project has no
// external image-hosting/asset pipeline anywhere, so a small
// geometric line-drawing is the only approach consistent with how every
// other visual here is built (CSS, not sourced images).
export default function ColonnadeMotif() {
  const columns = Array.from({ length: 8 }, (_, i) => i * 52);
  return (
    <svg
      viewBox="0 0 420 200"
      aria-hidden="true"
      focusable="false"
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        opacity: 0.08,
        pointerEvents: "none",
      }}
      preserveAspectRatio="none"
    >
      {/* pediment */}
      <polyline points="10,60 210,10 410,60" fill="none" stroke="var(--navy)" strokeWidth="3" />
      <line x1="0" y1="60" x2="420" y2="60" stroke="var(--navy)" strokeWidth="3" />
      {/* columns */}
      {columns.map((x) => (
        <g key={x}>
          <rect x={x + 15} y="65" width="6" height="110" fill="var(--navy)" />
          <rect x={x + 8} y="60" width="20" height="6" fill="var(--navy)" />
        </g>
      ))}
      {/* stylobate (base line) */}
      <line x1="0" y1="180" x2="420" y2="180" stroke="var(--navy)" strokeWidth="4" />
    </svg>
  );
}
