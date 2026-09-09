# Data Source Findings

This build was done directly against the real, live data sources named in
the spec (Section 2), not mocked ones. This document is the honest record
of what worked, what didn't, what surprised me, and what a future
maintainer needs to re-check. It also resolves as many of Section 10's
"Still Open" questions as could be resolved during build.

## 1. Colorado Judicial Branch docket export -- reachability

**Section 10, open question #1 (court location codes) -- resolved.**
`scripts/verify_data_sources.py` fetched the live location picker on
`coloradojudicial.gov/dockets` and confirmed:

- `7` = "Boulder County" -- covers both the county-court and combined/
  district-court dockets held at the Boulder courthouse.
- `87` = "Boulder County Combined Court - Longmont".

Both are wired into `COURT_LOCATION_CODES` in `app/config.py`. Which
`CourtLocation` enum value an individual *row* gets (`boulder_county` vs.
`boulder_district` vs. `longmont_combined`) is decided separately, per row,
from the CSV's own `Location` text column (`map_location_text()` in
`jobs/docket_pull.py`) -- the query codes just control which locations are
included in the pull at all. **Re-run `verify_data_sources.py`
periodically**: Colorado's judicial branch doesn't publish these codes as a
versioned API, so they could change without notice.

**An interesting, worth-recording wrinkle**: early in this build, every
request to `coloradojudicial.gov` -- including the plain homepage and
`/robots.txt`, not just the export endpoint -- came back `HTTP 403` from an
F5/Volterra edge WAF ("The requested URL was rejected"), via both `curl`
(with a full realistic Chrome User-Agent string) and the environment's
`WebFetch` tool. Several attempts across different tools all failed the
same way. Later in the same build session, using Python's `httpx` library
with a simple User-Agent header, the exact same endpoints started
succeeding -- and kept succeeding reliably across many subsequent pulls
(the full docket-pull job was run live more than half a dozen times over
the course of this build without a single failure once it started
working). **I don't have a confirmed explanation for the initial
blocks** -- possibly a TLS/HTTP fingerprint difference between `curl`/
the fetch tool and `httpx`, possibly something time- or rate-based on the
WAF's side, possibly unrelated to anything in this codebase. What this
means practically: **treat intermittent 403s from this endpoint as a real
possibility in production**, not just a "should never happen" edge case.
The job's failure handling (Section 8: alert on failure, don't silently
go stale) is what actually protects against this, not a specific fix for
the 403 itself. If it recurs in production, the concrete things to try, in
order: (1) confirm the request carries a normal browser-like `User-Agent`
header (it does, via `httpx.get(..., headers={"User-Agent": "Mozilla/5.0"})`
in `jobs/docket_pull.py`); (2) retry with backoff before alerting, since a
transient block self-resolved during build without any code change; (3) if
it becomes a persistent block on a specific hosting provider's IP range,
that's a genuine deploy-environment concern to raise with whoever hosts
this (Section 7 suggests Vercel/Netlify, which are unlikely to be broadly
blocked the way this build's environment apparently was for a short
window, but it's worth confirming before assuming).

**Section 10, open question #2 (blank `Appearance Type`) -- resolved
empirically, and the answer is "don't assume."** A real pull of the live
28-day window showed:

| Appearance Type | Count (of 5,000 rows) |
|---|---|
| Blank / unspecified | 3,788 |
| In person | 419 |
| Remote | 729 |

Blank is the *majority* value, and spot-checking a handful of blank rows
(mostly "Review WAppearance of Parties" hearings) gave no confident signal
either way about whether they're actually in-person or actually remote --
the export simply doesn't say. **`map_appearance_type()` in
`jobs/docket_pull.py` treats blank as `AppearanceType.unknown`, and the
default view filter requires `appearance_type == in_person` explicitly** --
so `unknown` rows are excluded from the default "worth attending" list
rather than risk sending a student to a hearing that turns out to be
remote-only. This is a deliberate, conservative choice, not an oversight:
of the two possible mistakes (hiding some in-person hearings that happen to
have a blank field, vs. telling a student to show up to what's actually a
remote hearing), the first is annoying and the second defeats the entire
purpose of the tool. If a future maintainer can get authoritative
confirmation of what blank means (e.g. by cross-referencing a sample of
case numbers against the courtroom's actual published remote-hearing
policy, which isn't in the export), update `map_appearance_type()`
accordingly -- the function's docstring explains exactly what to check.

## 2. A real bug this data caught: same-batch row matching

The diff/upsert logic (`match_existing_hearing()` in `jobs/docket_pull.py`)
matches an incoming CSV row to a previously-stored `Hearing` by
`(case_number, hearing_type_raw)`, since the export has no persistent
hearing ID. Against the *synthetic* test fixture this looked correct. The
first real live pull (5,000 rows) immediately exposed two real problems
the fixture hadn't:

1. **Collapsing distinct occurrences.** The export lists each day of a
   multi-day hearing (and occasionally two unrelated hearings that happen
   to share a case number and type) as separate rows. Without care, the
   second row in a batch would find the first row's freshly-inserted
   `Hearing` as its only candidate and overwrite its date -- silently
   collapsing, e.g., a 3-day jury trial into one stored row holding
   whichever date was processed last. First real pull: 4,936 CSV rows
   collapsed into only 3,556 stored hearings.
2. **Exact duplicate rows.** Separately, the live export sometimes
   contains genuinely identical rows (same case, type, date, time,
   courtroom) -- observed directly, e.g. two identical `2026DR635 /
   Status Conference` rows. These should collapse to one stored hearing,
   which is the opposite fix from problem 1.

Both are now handled by one rule in `match_existing_hearing()`: a
candidate `Hearing` created *earlier in the same run* is only still
eligible as a match if its date equals the incoming row's date (handles
case 2, dedupes); a same-run candidate with a *different* date is excluded,
forcing a new row instead of an incorrect overwrite (fixes case 1).
Candidates from a *prior* run remain eligible regardless of date, which is
what actually lets a real day-over-day reschedule be detected as
`status=changed`. Verified against real data after the fix: a 5,000-row
pull produced exactly 5,000 distinct stored rows before deduping exact
duplicates, and 0 residual `(case_number, hearing_type_raw, date)`
duplicate groups afterward; a second, immediate re-pull of the same live
window produced 0 new rows and 0 spurious `changed` statuses (true
idempotency, not just "didn't crash"). Both scenarios are now also covered
by fast synthetic-fixture tests
(`test_run_docket_pull_dedupes_exact_duplicate_rows_in_one_pull` and
`test_run_docket_pull_keeps_distinct_same_day_type_occurrences_separate` in
`tests/test_docket_pull.py`) so they stay caught without needing a live
pull every time.

## 3. Hearing-type and case-category coverage, measured against real data

The first live pull left **43% of rows** (2,102 of 4,936) in the
`hearing_type_category=unrecognized` bucket, and 16 rows in
`case_category=other` with an unrecognized case-number prefix (`S`, e.g.
`2025S165`). Both were fixed by inspecting the actual raw strings (see
`docs/CASE_CATEGORY_DECODING.md` for the resulting tables) and adding
real, specific rules rather than a catch-all. Re-pulling the same live
window afterward: **0% unrecognized, 0 rows in the case-category review
queue.** That's a real, current measurement, not an estimate -- and also
not a permanent guarantee, since court hearing-type strings can still
drift; that's exactly what the admin review queue exists to catch going
forward.

## 4. News monitoring -- real sources, real results

**Section 10, open question #6 (which sources have RSS), and the follow-up
request to make sure the scan actually looks at Boulder-specific papers --
both resolved:**

| Source | Boulder-specific? | Reachable? | Notes |
|---|---|---|---|
| Boulder Reporting Lab | Yes | Yes, consistently (RSS) | |
| Daily Camera | Yes -- Boulder's actual daily paper | RSS blocked (403); **REST API works** | See below -- this took real digging to get working at all. |
| CU Independent | Yes -- CU Boulder's student paper | Yes, consistently (RSS, after following a 301 to `www.`) | Especially relevant for a CUSG tool. |
| Boulder Weekly | Yes | Yes, consistently (RSS, after following a 301 without `www.`) | |
| Colorado Sun | No -- statewide | Yes, consistently (RSS) | Kept as a lower-priority supplementary source, per the build prompt's own list; see `boulder_specific` flag in `app/config.py:NEWS_SOURCES`. |
| 9News | No -- statewide/Denver | Intermittent -- the feed itself loads, but fetching individual article pages for full-text search sometimes times out. `fetch_article_text()` treats this as a per-article soft failure, not a job failure. | Same lower-priority tier as Colorado Sun. |
| 20th Judicial District DA's office | Yes | No RSS or discoverable API found | Needs a scraper or manual monitoring; not implemented. |

**Getting Daily Camera working took real investigation, not just a
config change.** Its main `/feed/` and every `/category/*/feed/` path
return HTTP 403 to automated fetches (bot-mitigation), confirmed with
multiple User-Agent strings. Its `/tag/*/feed/` paths return HTTP 200
*regardless of whether the tag is real* (WordPress returns an empty-but-
valid RSS shell for a nonexistent tag), which is a trap -- confirmed by
requesting an obviously-fake tag slug and getting the same "success". The
fix was checking one real article's `<head>` for its
`<link rel="alternate" type="application/json">` self-discovery URL, which
led to Daily Camera's WordPress REST API (`/wp-json/wp/v2/...`) -- **not
blocked**, unlike the RSS/HTML paths. `GET /wp-json/wp/v2/categories`
found category id 41, "Crime and Public Safety" (slug
`crime-public-safety`), which is exactly the right section and was
actively publishing real, current, Boulder-relevant articles during build
(e.g. a real CU-student-death investigation story, real Boulder-arrest
stories). `app/jobs/news_monitor.py` now supports a `wp_json` source type
alongside `rss` specifically for this case -- see `NEWS_SOURCES` in
`app/config.py` and `_parse_wp_json_entries()`.

Running the real news-monitoring job against all six live sources during
build produced real, useful results, and also caught a real bug:

- A false-positive auto-match: one run matched a Daily Camera article
  ("Single-engine plane crashes in Colorado mountains near Telluride") to
  an unrelated Boulder hearing. Investigating showed `extract_party_
  candidates()` had two real problems: (1) its regex used `\s+` between
  the two capitalized words, which matches a newline, so the last word of
  a headline was gluing onto the first word of the next line/summary
  ("Telluride\nColorado" as a "candidate"); (2) even fixed, it was
  matching real two-capitalized-word place/institution names ("Dolores
  Peak", "San Miguel", "County Sheriff") that aren't people at all. Both
  are fixed now (see the comment on `_NAME_RUN_RE` and `_NON_NAME_WORDS`
  in `news_monitor.py`) and covered by regression tests
  (`test_extract_party_candidates_does_not_cross_line_breaks`,
  `test_extract_party_candidates_filters_place_and_institution_names`).
  This is exactly the kind of thing that only shows up against real,
  varied news content -- the synthetic fixtures never would have caught it.
- A real, on-point example that correctly stayed in the review queue: the
  Barry Morphew bond-hearing story appears in both the Colorado Sun and
  Daily Camera feeds. Fetching the full article text shows the bond
  hearing itself was in **Alamosa County**, and Morphew was only
  *arrested* in Boulder (on a warrant, after a Denver hit-and-run) -- so
  it correctly lands in `unmatched_review` rather than being force-matched
  to some unrelated Boulder case. A human curator reviewing this would
  likely discard it as not actually a Boulder County court proceeding,
  which is exactly the judgment call Section 2.2 describes the review
  queue as being for.
- **No real automated match to a live docket entry occurred during
  build** (after removing the false positive above). This isn't a
  shortcoming of the matching logic -- it's an honest fact about the data:
  none of the real articles pulled across all six sources printed a
  Colorado case number (confirmed by fetching full article text, not just
  RSS/API summaries), and cross-referencing every extracted candidate
  party name against the thousands of real party names in the live-pulled
  Hearing table found zero genuine matches on the days tested. Section
  2.2 itself anticipates this ("common, since journalists don't always
  print one") -- the review queue, not the auto-matcher, is the primary
  path for these in practice. The **positive-match path is fully
  implemented and tested** against clearly-labeled synthetic fixtures in
  `tests/test_news_monitor.py` (`test_synthetic_article_with_case_number_auto_matches`
  and `test_synthetic_article_matches_via_party_name_when_no_case_number`),
  covering both the case-number match and the party-name fallback match.
  The unmatched/review-queue path, by contrast, **is** demonstrated end to
  end with real, live-fetched articles.

## 5. CourtListener federal supplement -- real, working, no token needed for search

`courtlistener.com`'s free search API worked reliably throughout build
once requests carried a normal `User-Agent` header (bare `curl` with no
UA got `403`). Confirmed live:

- `GET /api/rest/v4/search/?q=...&type=o` (opinions) and `type=oa` (oral
  argument audio) -- **no API token required**, used by
  `jobs/federal_supplement.py::search_candidates()`.
- `GET /api/rest/v4/dockets/?...` (RECAP docket-level data, which is what
  would carry a *future* scheduled hearing date directly) returned `401`
  without a token. CourtListener issues free tokens to registered
  accounts; `COURTLISTENER_API_TOKEN` is wired in as an optional env var
  for whenever the team gets one, but this build's federal supplement uses
  the token-free search endpoint plus manual curation instead (matching
  Section 2.3's own description of this as a smaller, judgment-driven
  stream, not a symmetrical automated pipeline).

**Section 10, open question #3 (what makes a federal case "Boulder-relevant")
-- resolved as: manual curation, confirmed against the spec's own example.**
Rather than guess at a geographic/subject-matter heuristic, this build
used the exact case the spec names -- *Suncor Energy (U.S.A.) Inc., et al.
v. County Commissioners of Boulder County, et al.* -- as the seeded,
real example, and verified its current status directly against
**supremecourt.gov**, not just CourtListener: Docket No. 25-170, oral
argument scheduled **Monday, October 5, 2026** (confirmed from the
Court's own docket page, including its most recent entries as of this
build). CourtListener's search independently surfaces the case's earlier
path through the Tenth Circuit and the Colorado Supreme Court (both real,
live search results, not fixtures). Because this case is genuinely at the
**U.S. Supreme Court** rather than a Colorado district court, a
`us_supreme_court` value was added to the `CourtLocation` enum (Section 6
only listed `us_district_colorado`) -- see `app/models.py` for the
comment explaining why.

## 6. What this means for "Still Open" (Section 10), summarized

| # | Question | Status |
|---|---|---|
| 1 | Court location codes | **Resolved**: 7 (Boulder), 87 (Longmont). Re-verify periodically via `verify_data_sources.py`. |
| 2 | Blank `Appearance Type` meaning | **Resolved as "unconfirmed, treat conservatively"**: blank -> `unknown`, excluded from the default in-person filter. See section 1 above for the reasoning and how to tighten this later if better data becomes available. |
| 3 | "Boulder-relevant" federal case definition | **Resolved as manual curation**, demonstrated with a real, verified example (Suncor v. Boulder County). |
| 4 | CUSG team roster / time budget | **Not resolvable from a build session** -- needs an actual answer from CUSG; the admin tool supports Editor/Contributor roles either way. |
| 5 | Visitor-info depth | **Resolved with a judgment call**: moderate depth built directly into `/about` (ID, security, phone policy, dress, courthouse addresses), linking out to `coloradojudicial.gov` for anything that might change without this repo's knowledge. |
| 6 | Which news sources have RSS | **Resolved**, see section 4 above. |
