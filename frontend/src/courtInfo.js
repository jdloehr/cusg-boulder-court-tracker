// Shared court-location metadata (Section 6's CourtLocation enum, plus the
// Colorado Supreme Court / Court of Appeals added on request -- Section
// 12's "expand the data" / "tag designating which court it's from").
// One source of truth so HearingList and HearingDetail can't drift apart.

export const COURT_LOCATION_LABELS = {
  boulder_county: "Boulder County Court",
  boulder_district: "Boulder Combined Court",
  longmont_combined: "Longmont Combined Court",
  us_district_colorado: "U.S. District Court, Colorado",
  us_supreme_court: "U.S. Supreme Court",
  colorado_supreme_court: "Colorado Supreme Court",
  colorado_court_of_appeals: "Colorado Court of Appeals",
  unknown: "Location unconfirmed",
};

// Short form for the badge shown on every hearing row/detail page --
// "Add a tag that designates which court it's coming from."
export const COURT_LOCATION_TAG = {
  boulder_county: "Boulder County",
  boulder_district: "Boulder Combined",
  longmont_combined: "Longmont",
  us_district_colorado: "U.S. District Ct.",
  us_supreme_court: "U.S. Supreme Ct.",
  colorado_supreme_court: "CO Supreme Ct.",
  colorado_court_of_appeals: "CO Ct. of Appeals",
  unknown: "Unconfirmed",
};

export const COURT_INFO = {
  boulder_county: {
    name: "Boulder County Justice Center",
    address: "1777 6th St, Boulder, CO 80302",
  },
  boulder_district: {
    name: "Boulder County Justice Center (Combined Court)",
    address: "1777 6th St, Boulder, CO 80302",
  },
  longmont_combined: {
    name: "Boulder County Combined Court -- Longmont",
    address: "1035 Kimbark St, Longmont, CO 80501",
  },
  us_district_colorado: {
    name: "Alfred A. Arraj U.S. Courthouse",
    address: "901 19th St, Denver, CO 80294",
  },
  us_supreme_court: {
    name: "Supreme Court of the United States",
    address: "1 First St NE, Washington, DC 20543 (seating extremely limited; usually livestreamed)",
  },
  colorado_supreme_court: {
    name: "Ralph L. Carr Colorado Judicial Center",
    address: "2 E 14th Ave, Denver, CO 80203 (also livestreamed -- see the Supreme Court Oral Arguments page)",
  },
  colorado_court_of_appeals: {
    name: "Ralph L. Carr Colorado Judicial Center",
    address: "2 E 14th Ave, Denver, CO 80203 (also livestreamed -- see the Court of Appeals Oral Arguments page)",
  },
  unknown: { name: "Location unconfirmed", address: "Check the official docket." },
};
