# Architecture

## Repo layout

```
backend/
  app/
    models.py            SQLAlchemy models (Section 6 schema + additions, see below)
    config.py             All environment-driven config in one place
    case_categories.py     Case-number -> category decoder (docs/CASE_CATEGORY_DECODING.md)
    hearing_types.py       Hearing-type -> category + plain-language decoder
    academic_calendar.py   Section 5.5 "is today a break/finals day" helper
    auth.py                JWT auth shared by the curation team AND CUSG Justices
    alerting.py             Job-failure alerting (console-log stub, Section 8)
    schemas.py             Pydantic request/response models
    routers/
      public.py             Fully public endpoints (Section 7: no login to browse)
      admin.py              Role-gated curation endpoints (Section 5.4)
      justices.py            CUSG Justice attendance + recommendation board (post-spec addition)
    jobs/
      docket_pull.py        Phase 1 core pipeline (Section 2.1)
      news_monitor.py        Phase 2 news enrichment (Section 2.2) -- RSS and WordPress
                             REST API sources, see docs/DATA_SOURCE_FINDINGS.md section 4
      federal_supplement.py  Phase 3 CourtListener search (Section 2.3)
      digest.py               Weekly email digest + academic-break suppression (Section 5.3/5.5)
      scheduler.py            APScheduler wiring for the above (Section 8)
    main.py                FastAPI app assembly
  scripts/
    run_docket_pull.py, run_news_monitor.py    Manual job entrypoints (cron calls these)
    seed_demo_data.py                            One-shot real-data demo seed (see README)
    create_admin_user.py                          Bootstrap a curation-team account
    create_justices.py                            Bootstrap the 7 real CUSG Justice accounts
    verify_data_sources.py                        Section 10 open-questions checker
  tests/                  55 tests: unit tests for both decoders, full pipeline tests
                          against a synthetic fixture, news-monitor tests against REAL
                          fetched RSS/REST-API fixtures, a live integration test against the
                          real CourtListener API, and full-stack TestClient tests for the
                          community-submission and Justice features. See each file's
                          docstring for what's real data vs. synthetic and why.
frontend/                 React (Vite) SPA -- list/detail/subscribe/recommendations/admin views
docs/                     This file, plus the three build-prompt-required writeups
```

## Deltas from the Section 6 schema (and why)

The build prompt's schema was implemented almost as-is; a few additions
were needed to actually implement behavior the prompt describes elsewhere:

- `Hearing.curated_blurb_draft` -- Section 5.4 describes a Contributor who
  can draft blurbs but can't publish, and an Editor who publishes. That
  needs a draft/published split somewhere; `curated_blurb` (public-facing)
  and `curated_blurb_draft` (pending) implement it.
- `Hearing.change_note` -- free-text explanation shown next to a
  `changed`/`cancelled` badge (e.g. "date 2026-09-22 -> 2026-09-24"),
  needed to make the `status` enum actually useful to a reader rather than
  just a badge with no explanation.
- `Hearing.court_location = us_supreme_court` -- added when the real,
  build-prompt-specified federal example (Suncor v. Boulder County) turned
  out to currently be at the Supreme Court, not a district court. See
  `docs/DATA_SOURCE_FINDINGS.md` section 5.
- `CaseCategory.juvenile` -- Section 6 doesn't list a case category enum
  value for juvenile cases (only a hearing-level `is_excluded` bool), but
  the exclusion logic needs to *detect* a juvenile case from its case
  number before excluding it, so the category has to exist somewhere.
- `ActivityLogEntry`, `JobRun` tables -- Section 5.4 ("Activity log") and
  Section 8 ("failure alerting", "unexpectedly empty data") both describe
  behavior that needs somewhere to persist state; neither table is listed
  in Section 6 but both are required by requirements stated elsewhere in
  the prompt.

Everything else matches Section 6 field-for-field.

## Additions made after the original spec (post-build requests)

Two features were added after the initial build, once it became clear the
tool's actual primary users are the CUSG Supreme Court itself, not just
pre-law students generally:

- **`CommunitySubmission`** (+ `Hearing.judge_name`): lets any site visitor
  propose a case summary or a judge's name for a hearing. Moderated, not
  immediate -- see `docs/EXCLUSION_LOGIC.md`'s "Visitor-submitted content"
  section for why and how.
- **`HearingAttendance`** and **`HearingRecommendation`**: let a CUSG
  Justice RSVP to a hearing (attending/not attending/maybe, with an
  optional note) and recommend a hearing to the rest of the court (with a
  note on why), landing on a dedicated public board at `/recommendations`.
  **No login at all**, by explicit request: the caller passes a
  `justice_id` (from the public `/api/justices` roster) directly in the
  request body rather than one being derived from a token. The trust
  model -- not enforced server-side, a deliberate choice -- is that the 7
  real Justices are the only realistic audience for this in practice and
  are expected to only act as themselves; see `set_attendance()`'s
  docstring in `app/routers/justices.py`. `AdminUser.is_justice` and
  `scripts/create_justices.py` still exist (a Justice who's *also* an
  Editor/Contributor still logs in for that), but that login is no longer
  required for attendance or recommendations specifically -- only for the
  separate Editor/Contributor curation tool in `app/routers/admin.py`,
  which stays role-gated (a more consequential system -- publishing public
  content, excluding hearings -- that these changes were not asked to
  touch).
- `CommunitySubmission` remains moderated (Editor approval before
  anything publishes) -- that gate is about *content quality/sensitivity*
  on a fully anonymous, un-identified input, not about restricting who can
  use the feature, so the "no login" changes above don't apply to it. See
  `docs/EXCLUSION_LOGIC.md`.
- **`CourtLocation.colorado_supreme_court` / `colorado_court_of_appeals`**:
  "expand the data" to Colorado's own two appellate courts, restricted to
  cases already newsworthy or likely to become so. `app/jobs/
  federal_supplement.py` was renamed to `appellate_supplement.py` and
  generalized (`PRESET_COURTS`, a `court` parameter already supported the
  mechanism) rather than building a parallel pipeline, since the real
  constraint is the same for federal and Colorado-appellate cases alike:
  CourtListener indexes real opinions for both `colo` and `coloctapp`
  (confirmed live) but has no oral-argument *scheduling* data for either
  -- Colorado's own calendars exist only as PDFs. `check_news_coverage()`
  cross-references a candidate's name against real articles the news-
  monitoring pipeline already gathered, surfacing an "In the news" hint in
  the admin search UI -- a curation aid, not a hard filter, since a
  genuinely newsworthy case shouldn't get hidden by a name-matching quirk.
  See `docs/DATA_SOURCE_FINDINGS.md` section 7 for the live findings this
  is built on.
- **`SubscriptionFilterType.new_recommendation`**: email the moment a
  Justice adds a hearing to the recommendation board -- reuses
  `SubscriptionFrequency.realtime_for_followed_case` (see that enum's
  updated comment in `app/models.py`) rather than adding a new frequency
  value, since both mean "immediately," not something case-specific.
- **`/welcome`**: a first-visit tour page, shown automatically once per
  browser (a `localStorage` flag, not a server-side "first login" concept
  -- there's no login for regular visitors) when landing on the plain
  homepage; always reachable from the nav afterward. A shared link
  straight to a specific hearing or the recommendations board is left
  alone rather than hijacked to the tour.

## Running locally

See the root `README.md` for exact commands. Short version: SQLite for
local dev (`DATABASE_URL` env var switches to Postgres for production with
no code changes -- see `app/db.py`), a single `seed_demo_data.py` script
that exercises the entire pipeline against real live data, `uvicorn` for
the API, `npm run dev` for the frontend.

## Known limitations / next steps

- **Adding a new enum value needs a manual Postgres migration in
  production, or it 500s.** Real bug, caught live: adding
  `CourtLocation.colorado_supreme_court` etc. to `app/models.py` and
  deploying was not enough -- `Base.metadata.create_all()` (this project's
  stand-in for a real migration tool) never runs `ALTER TYPE ... ADD
  VALUE` on a Postgres enum type that already exists, so the *existing*
  production database still only accepted the old set of values, and
  `POST /api/subscriptions` with the new `new_recommendation` filter type
  500'd until fixed by hand. Invisible in the test suite because it runs
  against SQLite, which has no native enum type to drift. Run
  `DATABASE_URL=<prod url> python scripts/check_enum_drift.py` after any
  deploy that touches an enum -- it compares every Python enum in
  `models.py` against the live Postgres types and prints the exact `ALTER
  TYPE` statements to fix any gap. Adopting Alembic (or another real
  migration tool) would make this automatic; deferred for this build's
  scope, per the project's original "shouldn't need a migration tool at
  CUSG's scale" framing, but this is the concrete cost of that choice.
- **Multi-day trials list one line per day, everywhere** (list view,
  digest email, etc.), because the docket export genuinely lists them that
  way and each day is a real, distinct scheduled event (see
  `docs/DATA_SOURCE_FINDINGS.md` section 2 for why these are intentionally
  kept as separate rows rather than collapsed). Confirmed against real
  data: a real multi-day jury trial in the seeded demo data correctly
  produces one digest line per day. This is accurate but a little verbose;
  grouping consecutive same-case-same-type days into one "Sept 14-18"
  entry in the UI/digest would be a good small follow-up, not a
  correctness fix.
- **Diffing is a heuristic, not a solved problem.** The docket export has
  no persistent hearing ID; matching across pulls is keyed on
  `(case_number, hearing_type_raw[, date])`. See
  `docs/DATA_SOURCE_FINDINGS.md` section 2 for the real bugs this
  surfaced and how they're handled. It's meaningfully more correct than a
  naive implementation, but a genuinely persistent ID from Colorado's side
  would obsolete this entire heuristic if one ever becomes available.
- **`docket_pull` does one DB round-trip per CSV row** (~20s for a 5,000-row
  pull in this build's environment). Fine for a daily batch job; if the
  window or court list grows a lot, batch-prefetching all rows matching
  the pull's set of case numbers up front (instead of querying per-row)
  would cut this down significantly.
- **Email and job-failure alerting are stubbed to console/log output**
  (`EMAIL_BACKEND` / `ALERT_BACKEND` = `"console"`), because no
  transactional-email or paging account exists for this build. The
  rendering/selection logic (who gets what digest, when it's suppressed
  for a break week, what triggers a realtime alert) is fully implemented
  and tested; only the actual "send" call is a stub. Swapping in a real
  provider is a small, isolated change in `app/jobs/digest.py` and
  `app/alerting.py`.
- **Hosting, Postgres, and a real cron scheduler are not deployed** --
  Section 7 calls for independent hosting (Vercel/Netlify) and this build
  had no such account to deploy to. `app/jobs/scheduler.py` implements the
  daily/weekly cadence in-process (fine at CUSG's scale per Section 7);
  moving it to the hosting platform's own cron/scheduled-function feature
  is a config change, not a rewrite.
