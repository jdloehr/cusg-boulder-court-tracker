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
- **`HearingAttendance`** and **`HearingRecommendation`**: let the 7 CUSG
  Justices RSVP to a hearing (attending/not attending/maybe, with an
  optional note) and recommend a hearing to the rest of the court (with a
  note on why), landing on a dedicated public board at `/recommendations`.
  Both reuse the *same* `AdminUser`/JWT login as the Editor/Contributor
  curation team rather than a parallel auth system -- see `AdminUser`'s
  docstring in `app/models.py` for why `role` (curation) and `is_justice`
  (court membership) are independent fields on one account rather than a
  single combined enum: the same small group of real people plausibly
  wears both hats, and forcing two separate logins for one person would be
  pure friction with no security benefit at this scale (7 named
  individuals, `scripts/create_justices.py`).
- These two features share one instinct with the original Section 4
  guardrails: something public-facing proposes, someone with real
  authority (an Editor, or the submitting Justice's own name) is
  accountable for it -- see `docs/EXCLUSION_LOGIC.md`.

## Running locally

See the root `README.md` for exact commands. Short version: SQLite for
local dev (`DATABASE_URL` env var switches to Postgres for production with
no code changes -- see `app/db.py`), a single `seed_demo_data.py` script
that exercises the entire pipeline against real live data, `uvicorn` for
the API, `npm run dev` for the frontend.

## Known limitations / next steps

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
