import { useId } from "react";

// Court Passport redesign: the circular "stamp" motif used across several
// pages (ring text on a path, two short center lines, slight rotation) --
// hand-authored inline SVG, same convention as ColonnadeMotif.jsx. The
// ring-text path id uses useId() so multiple stamps on one page never
// collide. Decorative only -- aria-hidden.
export default function StampMotif({
  size = 150,
  color = "#1B2A38",
  fillOpacity = "rgba(250,248,243,0.92)",
  line1 = "OPEN",
  line2 = "COURT",
  rotation = -14,
  ...props
}) {
  const rawId = useId();
  const pathId = `stamp-${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 150 150"
      aria-hidden="true"
      style={{ transform: `rotate(${rotation}deg)` }}
      {...props}
    >
      <circle cx="75" cy="75" r="70" fill={fillOpacity} stroke={color} strokeWidth="3" />
      <circle cx="75" cy="75" r="62" fill="none" stroke={color} strokeWidth="1.5" />
      <circle cx="75" cy="75" r="39" fill="none" stroke={color} strokeWidth="1.5" />
      <path id={pathId} d="M75 75 m-50 0 a50 50 0 1 1 100 0 a50 50 0 1 1 -100 0" fill="none" />
      <text fontFamily="IBM Plex Mono, monospace" fontSize="10.5" fontWeight="500" fill={color} letterSpacing="2">
        <textPath href={`#${pathId}`}>COURT PASSPORT &bull; BOULDER COLORADO &bull; </textPath>
      </text>
      <text x="75" y="76" textAnchor="middle" fontFamily="Source Serif 4, Georgia, serif" fontWeight="900" fontSize="19" fill={color}>
        {line1}
      </text>
      <text x="75" y="93" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontWeight="500" fontSize="11" letterSpacing="1.5" fill={color}>
        {line2}
      </text>
    </svg>
  );
}
