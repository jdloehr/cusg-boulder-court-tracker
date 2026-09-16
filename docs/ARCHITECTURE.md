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
    livestream.py            Court-livestream link defaults by court_location (Phase-2 doc Section 2)
    moderation.py            Basic spam/profanity filter for the Archive's unmoderated public input
    schemas.py             Pydantic request/response models
    routers/
      public.py             Fully public endpoints (Section 7: no login to browse); also
                             data-status + manual-refresh (Phase-2 doc Section 1)
      admin.py              Role-gated curation endpoints (Section 5.4)
      justices.py            CUSG Justice attendance + recommendation board (post-spec addition;
                             now login-gated, see "Phase 2" section below)
      archive.py              Archive & Reflections (Phase-2 doc Section 5)
    jobs/
      docket_pull.py        Phase 1 core pipeline (Section 2.1)
      news_monitor.py        Phase 2 news enrichment (Section 2.2) -- RSS and WordPress
                             REST API sources, see docs/DATA_SOURCE_FINDINGS.md section 4
      appellate_supplement.py  CourtListener search (Section 2.3), generalized to also cover
                                Colorado's own Supreme Court/Court of Appeals
      digest.py               Weekly email digest + academic-break suppression (Section 5.3/5.5);
                               also the new-recommendation email triggers (Phase-2 doc Section 4)
      scheduler.py            APScheduler wiring for the above (Section 8), fixed 7am
                              America/Denver schedule (Phase-2 doc Section 1)
    main.py                FastAPI app assembly
  scripts/
    run_docket_pull.py, run_news_monitor.py    Manual job entrypoints (cron calls these)
    seed_demo_data.py                            One-shot real-data demo seed (see README)
    create_admin_user.py                          Bootstrap a curation-team account
    create_justices.py                            Bootstrap the 7 real CUSG Justice accounts
    check_enum_drift.py                           Post-deploy Postgres enum-drift checker
    verify_data_sources.py                        Section 10 open-questions checker
  tests/                  ~90 tests: unit tests for both decoders, full pipeline tests
                          against a synthetic fixture, news-monitor tests against REAL
                          fetched RSS/REST-API fixtures, a live integration test against the
                          real CourtListener API, and full-stack TestClient tests for the
                          community-submission, Justice, Archive, and auto-update features.
                          See each file's docstring for what's real data vs. synthetic and why.
frontend/                 React (Vite) SPA -- list/detail/subscribe/recommendations/archive/admin views
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

## Phase 2 additions (a follow-up build-prompt document)

A second round of features, specified in a separate follow-up document
once the site was already live. Two decisions from that document
deliberately reverse choices made in the round above -- flagged and
confirmed with the user rather than applied silently, since they directly
contradict an explicit prior instruction:

- **Attendance and recommendations now require a real Justice login
  again** (`require_justice`), reversing the "no login at all, justice_id
  in the request body" design from the round above. `AttendanceIn` and
  `RecommendationIn` no longer take a `justice_id` field; identity comes
  from the authenticated user. `RecommendationIn.note` also became
  *required* (a "short required reason"), where it was previously
  optional.
- **Justices and the Editor/Contributor curation role stay separate
  accounts/authority**, confirmed explicitly rather than merging them the
  way the new document's Section 3 assumed ("the 7-8 Justices are the
  same people as the Editor role"). `require_justice` still checks
  `AdminUser.is_justice`, independent of `role`.

New, purely additive features from that document:

- **`Hearing.livestream_source_type` / `livestream_url`** (`app/
  livestream.py`): defaulted by `court_location` at hearing-creation time
  (docket-pull and the appellate-candidate publish endpoint both call
  `default_livestream()`). Built from real findings, not assumptions:
  `live.coloradojudicial.gov` is real and reachable, but its county picker
  is populated by client-side JS with no discoverable deep-link query
  parameter (checked live -- the page's initial HTML has only one
  hardcoded `<option>`), so state hearings link to the portal itself
  rather than a fabricated per-county URL. SCOTUS gets a real, confirmed
  live-audio URL. Federal district court gets no default (no general
  public video livestreaming) unless a curator supplies a specific
  audio-access line when publishing.
- **`GET /api/data-status` + `POST /api/refresh`**: a real "last updated"
  timestamp (the most recent successful `docket_pull` `JobRun.finished_at`
  -- no new tracking table) and a public, globally-cooled-down
  (`REFRESH_COOLDOWN_MINUTES`, default 20) manual refresh button. The
  refresh runs as a FastAPI `BackgroundTask` so the request returns
  immediately rather than holding the connection open for however long a
  live docket-export fetch takes.
- **Fixed 7:00 AM Mountain Time schedule**: `app/jobs/scheduler.py`'s
  APScheduler `CronTrigger` now takes `timezone="America/Denver"`
  (handles the MST/MDT switch correctly year-round on its own). The
  GitHub Actions cron (`.github/workflows/scheduled-jobs.yml`) has no
  timezone support at all, so it's pinned to `13:00 UTC` (correct for
  MDT, off by an hour during MST) with the drift documented in a comment
  rather than silently wrong.
- **`ArchiveEntry`** (`app/routers/archive.py`): a public, browsable,
  reverse-chronological record of hearings actually attended and written
  up, restricted to hearings whose date has already passed. Two
  submission paths converge on one `POST /api/archive` endpoint,
  distinguished by a new `get_optional_admin()` auth dependency in
  `app/auth.py` (returns `None` instead of raising when there's no/an
  invalid token, unlike `get_current_admin`): a logged-in Justice's
  "Mark Attendance" (reflection optional, auto-added to `attendees`) vs.
  anyone's "Submit a Summary" (reflection required, a free-text display
  name, no account). The public path publishes immediately with no
  approval queue -- a deliberate choice, unlike `CommunitySubmission`'s
  moderation queue -- so it leans on after-the-fact safeguards instead:
  `app/moderation.py`'s basic spam/profanity filter at submission time,
  `submitter_ip` logged internally (never exposed via `ArchiveEntryOut`),
  and any Justice can edit or remove any entry afterward.
- **`SubscriptionFilterType.new_recommendation` now also triggers a
  second, unconditional email to every active Justice**
  (`notify_all_justices_of_new_recommendation` in `app/jobs/digest.py`),
  distinct from the existing subscriber-based
  `notify_subscribers_of_new_recommendation` -- two different audiences,
  both notified from the same `create_recommendation` call.
- **Security review** (the doc's Section 6) -- see
  `docs/SECURITY_REVIEW.md` for what applies to this app's actual
  architecture (a JWT-bearer API, not cookie-session auth) and what
  doesn't.

## Phase 3 additions (Justice accounts & public profiles)

A third follow-up document, again specified once the Phase-2 features
were already live. One decision from that document reverses a choice
confirmed explicitly in the Phase-2 round above:

- **Every Justice account now also gets full curation (Editor) access**,
  reversing Phase 2's explicit "keep Justices and the Editor/Contributor
  role separate" decision. Re-flagged and re-confirmed with the user
  before building (the new document's Section 2 again assumed the two
  were the same thing), same as Phase 2's own reversal was. Implemented
  as a data fact, not a permission-check change: provisioning a Justice
  (invite-accept, and a one-time startup backfill for the original 7)
  sets `role=AdminRole.editor` directly, so `require_editor`'s own check
  (`role == editor`) never had to change -- the real Editor-vs-Contributor
  distinction for curation work is untouched. See `AdminUser`'s docstring
  in `app/models.py`.

New, purely additive features from that document:

- **Invite-link provisioning** (`app/routers/account.py`, `AdminInvite`):
  an Editor/Justice enters a real person's name+email
  (`POST /api/admin/invites`); a one-time, 48-hour token (stored only as
  its SHA-256 hash -- `app/auth.py::hash_token`) is emailed (and returned
  directly in the API response too, since no real transactional-email
  account exists yet -- see Email delivery below) as
  `{FRONTEND_URL}/accept-invite/{token}`. Accepting it
  (`POST /api/invites/{token}/accept`) creates or updates that email's
  `AdminUser` and logs them straight in. Not open self-registration or a
  shared code (the document's own Section 6.1 choice, confirmed) -- only
  someone already holding curation access can mint an invite.
- **Forgot/reset password** (`PasswordResetToken`,
  `POST /api/auth/forgot-password` + `POST /api/auth/reset-password/
  {token}`): same single-use, expiring, hashed-token pattern as invites.
  `forgot-password` always returns an identical generic response whether
  or not the email matches an account, so the endpoint can't be used to
  enumerate the roster.
- **Password strength + login rate-limiting**
  (`app/auth.py::validate_password_strength`, wired into both the invite-
  accept and password-reset schemas; `POST /api/admin/login` now calls
  `check_rate_limit` per IP, 10 attempts/10 minutes) -- the doc's Section
  5 carried Phase 2's security-review recommendations forward given
  Justice accounts now have real write power (recommendations, editable
  public profiles) plus, as of this round, an actual password-choosing
  step for the first time (Phase 2's justices had random,
  script-generated passwords only). 2FA is still explicitly deferred, same
  reasoning as Phase 2's security review -- a small, invite-gated roster
  is a narrow attack surface.
- **Public Justice profiles** (new `AdminUser` columns: `bio`,
  `year_or_major`, `why_care`, `fun_fact`, `photo_data`,
  `photo_content_type`): a Justice edits only their own profile
  (`PATCH /api/justices/me/profile`, identity from the login, never a
  caller-supplied ID) via a "Meet the Justices" directory
  (`GET /api/justices`, now returning full profile fields) and individual
  profile pages (`GET /api/justices/{id}`) at a stable URL. Explicit
  choice (Section 6.4): profiles are always public with no per-Justice
  hide toggle.
- **Real photo upload** (`app/photo.py`, explicit choice over an
  avatar/emoji picker): validated by actually decoding it with Pillow
  (not trusting the declared Content-Type or file extension), capped at
  5MB raw / 800px on the long edge after resizing, and always re-encoded
  to a fresh JPEG -- which is what actually strips EXIF/metadata (Pillow's
  `save()` doesn't carry the source file's metadata forward unless you
  explicitly pass it back in). Stored directly as bytes in Postgres
  (`LargeBinary`), not a separate object-storage service this project
  doesn't have provisioned -- a handful of re-encoded headshots is a
  trivial amount of data for a database column at this scale.
- **Linked Justice names everywhere one appears** (new shared
  `components/JusticeLink.jsx` + one CSS class,
  `.justice-link`/`styles.css`): the recommendation callout, attendance
  rows, and an Archive entry's attendee list and byline all link a
  Justice's name to their profile. `RecommendationOut` gained
  `justice_id` (trivial -- always known at write time).
  `HearingAttendance` rows already carried `justice_id`. Archive
  attendees needed more care: `ArchiveEntry.attendees` stays a plain
  JSON list of display-name strings (a Justice editing the list can
  still type any name, including a non-Justice's -- changing that to
  ID-only storage would have been a real behavior regression), so
  `AttendeeOut` resolves each name against the *current* roster by exact
  match at read time (`routers/archive.py::_resolve_attendees`) -- a name
  that doesn't match just renders as plain, unlinked text, not an error.
  The submitter byline uses a new `ArchiveEntry.submitted_by_justice_id`
  column instead (set directly from the authenticated Justice at write
  time, so it doesn't depend on name-matching, but only populated for
  entries created after this column existed -- older entries' bylines
  just don't link, an honest degradation rather than a backfill guess).

## Running locally

See the root `README.md` for exact commands. Short version: SQLite for
local dev (`DATABASE_URL` env var switches to Postgres for production with
no code changes -- see `app/db.py`), a single `seed_demo_data.py` script
that exercises the entire pipeline against real live data, `uvicorn` for
the API, `npm run dev` for the frontend.

## Known limitations / next steps

- **Adding a new enum value, or a new column on an existing table, needs
  a Postgres schema patch in production, or it 500s.** Real bug, hit
  twice: first, adding `CourtLocation.colorado_supreme_court` etc. to
  `app/models.py` and deploying was not enough -- `Base.metadata.
  create_all()` (this project's stand-in for a real migration tool) never
  runs `ALTER TYPE ... ADD VALUE` on a Postgres enum type that already
  exists, so `POST /api/subscriptions` with the new `new_recommendation`
  filter type 500'd until fixed by hand. Second, the Phase-2 round added
  `livestream_source_type`/`livestream_url` columns to the pre-existing
  `hearings` table -- same root cause, one level up: `create_all()` only
  creates whole missing *tables*, so a table that already exists never
  gets ALTERed for a new column, and every `/api/hearings` request 500'd
  in production after that deploy. Both are invisible in the test suite
  because it runs against SQLite, which recreates cleanly from a wiped
  file and has no native enum type to drift in the first place.

  The second occurrence also surfaced a hosting constraint that made the
  first occurrence's fix (a manual script, run by hand in Render's Shell
  tab) impossible to repeat: **this project's Render plan doesn't include
  Shell access.** So `app/migrations.py` now runs small, hand-written,
  idempotent schema patches automatically on every backend startup --
  covering new columns/types on already-existing tables without needing
  anywhere to run a one-off command by hand. `scripts/check_enum_drift.py`
  (a read-only diagnostic, not a fix) still needs to run from a machine
  that has the production `DATABASE_URL` -- see `docs/DEPLOYMENT.md`'s
  "Schema changes: no Shell access on this Render plan" for how, now that
  Render's Shell tab isn't an option. Adopting Alembic (or another real
  migration tool) would replace both of these with one consistent
  mechanism; deferred for this build's scope, per the project's original
  "shouldn't need a migration tool at CUSG's scale" framing, but this is
  the concrete, now twice-paid cost of that choice.
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
