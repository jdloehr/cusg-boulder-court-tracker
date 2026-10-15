// Court Passport rename: a single source of truth for the site's name/byline/
// digest name, imported everywhere instead of hardcoding the string a second
// time per file. index.html's <title>/meta tags are NOT React-rendered (Vite
// doesn't template index.html at runtime), so those are edited by hand
// directly in that file, not imported from here.
export const SITE_NAME = "Court Passport";
export const SITE_BYLINE = "A project of the University of Colorado Judicial Branch";
export const DIGEST_NAME = "The Court Passport Digest";
export const SITE_DESCRIPTION =
  "Upcoming Boulder-area jury trials and oral arguments worth watching, for pre-law students and anyone interested in the field of law.";
