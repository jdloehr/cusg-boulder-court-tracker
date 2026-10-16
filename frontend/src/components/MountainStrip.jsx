// Court Passport redesign: the flat Flatirons-skyline strip used along the
// bottom of several header bands -- a back range plus 3 pointed front
// slabs, colors passed as props so each page can tint it to match its own
// band color. Hand-authored inline SVG, same convention as
// ColonnadeMotif.jsx; geometry copied directly from the mockups.
export default function MountainStrip({
  height = 110,
  backColor = "#6F7F55",
  slab1Color = "#465331",
  slab2Color = "#5B6944",
  slab3Color = "#3B4829",
  ...props
}) {
  return (
    <svg width="100%" height={height} viewBox="0 0 1440 110" preserveAspectRatio="none" aria-hidden="true" {...props}>
      <path
        d="M0 110 V60.5 L120 30.8 L260 55 L420 13.2 L600 60.5 L760 33 L940 66 L1100 22 L1280 55 L1440 37.4 V110 Z"
        fill={backColor}
      />
      <polygon points="120,110 232,11 268,110" fill={slab1Color} />
      <polygon points="230,110 340,0 384,110" fill={slab2Color} />
      <polygon points="342,110 430,24.2 468,110" fill={slab3Color} />
    </svg>
  );
}
