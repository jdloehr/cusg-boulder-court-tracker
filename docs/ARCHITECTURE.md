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
- **Self-service invite requests, added as a follow-up** once "you need
  an existing Editor/Justice to invite you before you can invite anyone,
  including yourself" turned out to be a real bootstrapping problem in
  practice. `JusticeAllowlistEntry` is the actual gate (an Editor adds a
  real person's email once); `POST /api/justices/request-invite` is
  public and lets that person trigger their own invite send by entering
  their own email -- an unlisted email gets the same generic response
  either way (`{"status": "ok", ...}`, no send), same anti-enumeration
  reasoning as forgot-password. Shares `_issue_invite()` with the
  Editor-direct flow above rather than duplicating the token/expiry/
  invalidate-previous-invite logic. Purely additive -- the direct flow
  still works unchanged for an Editor who'd rather just invite someone
  themselves.
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
- **Real, optional email delivery** (`app/jobs/digest.py::send_email`,
  `EMAIL_BACKEND=sendgrid`): added once invite links became something a
  real person actually needs delivered, not just logged. A raw
  `httpx.post()` to SendGrid's HTTP API rather than pulling in their SDK
  (or a new HTTP-client dependency at all -- `httpx` was already used
  everywhere else in this codebase) for what's a single API call. Never
  raises on failure -- logs loudly and moves on, since every caller
  (invite creation especially) already has a fallback: the invite link
  itself is also returned directly in the API response.

## Phase 4 additions (security hardening + CUSG Judicial Branch branding)

A fourth follow-up document, prompted by the site being about to be
linked from the official CU Boulder CUSG website -- a real change in risk
profile (more traffic, implicit official association, more attractive to
casual probing) even though nothing about the app's own purpose changed.
Explicitly a security-and-copy pass layered on top of everything already
built, not a rebuild -- every existing feature keeps working unchanged.

**Security (Section 2):**

- **Response security headers** (`app/security_headers.py`,
  `SecurityHeadersMiddleware`): `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-
  origin`, HSTS, and a locked-down `Content-Security-Policy` (`default-
  src 'none'`, since this is a JSON API with no scripts/styles/frames of
  its own to allow) on every backend response. FastAPI's own interactive
  docs (`/docs`, `/redoc`) are disabled outright in production
  (`ENVIRONMENT=production`) rather than exempted from the CSP for real --
  no external integrators need them, and they're pure attack-surface once
  linked from an official page. The frontend gets its own, separately-
  tuned CSP via `frontend/vercel.json`'s `headers` block (needs `'unsafe-
  inline'` for `style-src` -- React's `style={{...}}` prop sets CSS
  properties through the CSSOM, not the HTML `style=""` attribute, so it
  isn't actually gated by CSP either way, but this wasn't verified
  rigorously enough to risk tightening further and silently breaking the
  site's layout; `script-src 'self'` stays strict, which is where nearly
  all of CSP's real XSS-prevention value comes from anyway).
- **A real CORS allow-list** (`ALLOWED_ORIGINS` in `app/config.py`)
  replaces `allow_origins=["*"]` -- a gap flagged as far back as the
  original build ("tighten... in production") and left alone until this
  round gave a concrete reason to close it.
- **Every public write endpoint is now rate-limited and length/format-
  validated**, not just the ones earlier phases happened to cover:
  `POST /api/subscriptions` and `POST /api/hearings/{id}/submissions`
  (the community "add case details" form) were the two real gaps --
  `POST /api/invites/{token}/accept` and `POST /api/auth/reset-password/
  {token}` also got a per-IP rate limit as belt-and-suspenders, even
  though their tokens are already high-entropy enough that guessing
  isn't computationally feasible. A shared `validate_email_format()`
  (`app/schemas.py`) -- a practical `word@word.word` check plus a length
  cap, not a new `email-validator` dependency for full RFC grammar -- is
  now applied to every email field in the API, including ones (login,
  invite/allowlist emails) that had none before. The community-
  submission endpoint also now runs through `app/moderation.py`'s spam/
  profanity filter, same as the Archive's public path already did.
- **Account lockout** (`AdminUser.failed_login_attempts` /
  `locked_until`, `app/routers/admin.py`): 10 failed attempts locks an
  account for 15 minutes, regardless of which IP the attempts came from
  -- layered on top of the existing per-IP login rate limit (that one
  stops one address hammering any account; this one stops a distributed
  attempt spread across many IPs aimed at one specific account).
- **Real TOTP two-factor authentication** (`app/totp.py`, using `pyotp`
  for the RFC 6238 math and `qrcode` -- already-installed `Pillow` does
  the image encoding -- for a scannable setup QR code): `POST /api/
  account/2fa/setup` → `.../confirm` → enabled, available to any
  authenticated account via `get_current_admin` (not Justice-specific).
  Login gets a third outcome beyond 200/401: **428** ("right password,
  now send a code") so the frontend can prompt for one without it
  counting as a failed attempt. Eight single-use backup codes are
  generated at confirm time, shown once, and stored only as hashes
  (`hash_token`, same treatment as invite/reset tokens) -- losing a phone
  shouldn't mean losing an account on a small, invite-gated roster where
  that's a real support burden, not a hypothetical one.
- **"Report" flagging** (`ContentReport`, `app/routers/reports.py`): a
  public, rate-limited `POST /api/reports` on every Archive entry and
  recommendation (both publish with no pre-review), notifying every
  Justice -- Section 5.4's explicit choice over a single designated
  moderator, same audience/reasoning as the existing new-recommendation
  email. Doesn't remove or hide content itself; lands in the dashboard's
  new Reports queue (`GET/POST /api/admin/reports...`) with a content
  summary for triage, and an Editor resolves it by hand using the
  edit/delete tools that already exist for both content types.
- **Email authentication (SPF/DKIM/DMARC) and the CU IT/CUSG-advisor
  review process** (Sections 2.4 and 2.7) are explicitly *not* code --
  the first needs DNS control over whatever domain `EMAIL_FROM_ADDRESS`
  is on (SendGrid's dashboard walks through the exact records once a
  domain is chosen), and the second depends on CU's own internal policy,
  which nothing in this codebase can determine. Both flagged for the
  CUSG team to actually do, not guessed at here.
- **Privacy notice** (`frontend/src/pages/Privacy.jsx`, linked from the
  footer): plain-language, not a legal document -- what's collected
  (emails, names, IPs on unmoderated paths, profile photos), why, and how
  to get it removed.

**Branding (Section 3):** a text-only affiliation credit ("A project of
the CUSG Judicial Branch," footer + a new `/about-project` page) and a
link to the real, verified official CUSG Judicial Branch page
(`colorado.edu/cusg/about-us/judicial-branch`) -- confirmed live and
current (same Chief Justice/Deputy Chief Justice names already seeded in
`scripts/create_justices.py`) rather than assumed. Explicit choice
(confirmed with the user): no CU Boulder logo/wordmark/trademarked colors
at all, matching the doc's own stated default -- using official university
marks without clearance from CU's brand office was flagged as a real risk
to CUSG, not just a formality. The framed audience broadened from
"pre-law students" to "pre-law students, or anyone else interested in the
field of law" everywhere that copy appeared (header tagline, Welcome
page, README, meta description/Open Graph tags).

**Follow-up: real Justice login emails.** The 7 seeded accounts started
on placeholder `@cusg-justices.local` addresses (Phase 2:
`scripts/create_justices.py`'s own comment already anticipated this --
"adjust to real CU email addresses whenever the team has them"). Once
the real addresses existed, updating them ran through
`app/account_email_updates.py`, driven by a `JUSTICE_EMAIL_UPDATES` env
var (an old-email -> new-email JSON mapping) rather than a hardcoded
mapping or a one-off script with real addresses typed into it -- real
people's real email addresses have no reason to live in this public
repository's source or git history, the same reasoning `SENDGRID_API_KEY`
and `FRONTEND_URL` are env vars instead of constants. Runs automatically
at every startup (same "no Shell access" reasoning as `app/
migrations.py`) and is naturally idempotent: once an address has changed,
the old one in the mapping no longer matches anything. See
`docs/DEPLOYMENT.md`'s "Updating a Justice's login email."

## Phase 6 additions (news-to-case matching fix)

A fifth follow-up document: the news-monitoring pipeline was pulling
articles, but almost none were ending up linked to hearings. The doc's
own diagnosis-first instruction (Section 1) was followed literally,
against real production data, before writing any new matching logic --
see `docs/DATA_SOURCE_FINDINGS.md` section 4a for the full account. Short
version: the doc's assumed root cause (a `LASTNAME, FIRSTNAME` vs
`Firstname Lastname` format mismatch) turned out to be wrong -- real
production data confirmed both sides already use the same word order --
and the real problem was the review queue being overwhelmed with non-
court content from unfiltered general-news feeds, not silently-discarded
good matches.

- **Matching logic moved to a new module**, `app/jobs/news_matching.py`,
  shared between ingestion (`app/jobs/news_monitor.py`) and the
  retroactive re-match pass (below) so both use identical scoring:
  - `name_match_score()`: last name must match exactly (the anchor
    signal); first name tolerates an exact match, an initial-vs-full-name
    match, or a fuzzy/nickname difference (`difflib.SequenceMatcher`) --
    real improvements over the old exact-substring check, just not the
    fix for the format assumption that turned out to be correct already.
  - Date-proximity gating (`DATE_WINDOW_DAYS = 21`): a name candidate is
    only scored against hearings within three weeks of the article's
    publish date, applied as a SQL-level pre-filter (not just a post-hoc
    check) for real query-cost reasons at this project's actual scale
    (thousands of hearings).
  - Category-consistency downweighting: an article whose language clearly
    reads as one category disagreeing with the candidate hearing's actual
    category demotes an otherwise-strong match from high to medium
    confidence rather than blocking it outright (Section 2's own
    framing: "a signal to lower confidence, not auto-match").
  - `has_court_relevance()`: the relevance gate that came out of the real
    diagnosis, not the doc's original ask -- an article with no case
    number, no name candidate, and no court-relevant language at all
    (`should_discard`) is discarded outright rather than queued, which is
    what actually made the queue usable again.
- **Confidence tiers** (`MatchStatus.suggested_pending_review`,
  `MatchStatus.discarded` -- two new enum values on the pre-existing
  `matchstatus` type, plus a new `matchconfidence` type/column): case
  number match, or a strong name match with date-proximity agreement, is
  `auto_matched`; a real but less-certain candidate is
  `suggested_pending_review` (hearing_id set, awaiting a one-click
  confirm/reject); no case number/no name/no court-relevant language is
  `discarded`. `Hearing.has_news_mention` was quietly wrong under the old
  "anything but unmatched_review counts" logic once these new statuses
  existed (a merely-suggested or discarded mention would have counted as
  "in the news") -- fixed to an explicit allowlist
  (`auto_matched`/`manually_linked`).
- **Review queue UX** (`app/routers/admin.py`,
  `frontend/.../AdminDashboard.jsx`): the queue now shows suggested
  matches with their candidate hearing front and center and one-click
  confirm/reject, a "link by case number" field (no more pasting a raw
  hearing UUID) alongside the still-supported hearing-ID path, and a
  visible pending-count badge on the sidebar tab itself -- visible before
  ever opening the tab, directly answering Section 4's "so it isn't easy
  to forget about."
- **Retroactive re-matching** (`app/jobs/news_monitor.py::
  retroactively_rematch`, called from `app/jobs/docket_pull.py` right
  after every successful pull): re-scores unresolved rows from the last
  30 days against the *current* Hearing table, since a story can run
  before its case's docket entry exists yet. Only ever promotes toward a
  more confident outcome, never demotes or re-discards a row a human may
  already be looking at. Wrapped so a failure here never turns a
  successful docket pull into a reported one.
- **Diagnosis logging** (Section 1's own ask): one structured log line
  per article -- case numbers found, party candidates found, the full
  match-evaluation signals dict, and the final outcome -- plus those same
  signals persisted on `NewsMention.match_signals` (JSON) so this is
  inspectable after the fact, not just at the moment a log line scrolled
  by.
- **Two pre-existing, unrelated flaky tests fixed along the way**
  (`test_hearing_sorting.py`, `test_docket_pull.py`): both hardcoded a
  fixed calendar date as a stand-in for "today," which broke the moment
  real wall-clock time passed that date -- caught because the full test
  suite was run as part of this phase's own verification, not something
  this phase's changes caused.

## Phase 6.2 additions (consolidated update: branding, homepage, availability)

A consolidated doc covering work that was designed earlier but never
shipped, plus one new ask (extending availability matching to public
visitors with a matching newsletter opt-in). Non-negotiable per the doc:
nothing already working regresses.

- **Justice profile consolidation** (`frontend/src/pages/Justices.jsx`):
  the old click-through directory (circular photo tiles, each linking to
  its own `/justices/:id` page) is gone. Every Justice's full profile now
  renders inline on one continuous page, alternating photo side per
  entry, square-framed photos. `JusticeLink.jsx` now links to
  `/justices#justice-<id>` instead of a separate URL; the old
  `/justices/:id` route redirects there (`JusticeIdRedirect` in
  `App.jsx`) so any previously-shared link still resolves. React Router
  doesn't scroll to a `#fragment` on its own for an in-app navigation, so
  `Justices.jsx` does it manually on mount/hash-change.
- **"CUSG Court," never "Supreme Court"** for this project's own team:
  8 self-referential mentions across frontend copy and two backend
  docstrings changed. `CourtLocation.us_supreme_court`/
  `colorado_supreme_court` and every other reference to the real U.S./
  Colorado Supreme Court (the federal case supplement, `courtInfo.js`,
  the SCOTUS live-audio link) are untouched -- those are real external
  courts, not this project's self-reference.
- **Homepage rebuilt as a distinct route** (`frontend/src/pages/Home.jsx`,
  new): `/` is now a marketing/landing page (hero, "This Week's Pick"
  spotlight, a pull-quote, a weekly-list preview, a dark-navy about band);
  the filterable docket (`HearingList.jsx`, internals unchanged) moved to
  `/hearings`. The header nav shrank to Calendar/Recommendations/Archive/
  Meet the Justices plus a low-emphasis "Justice Sign In" link (moved
  from the footer); Welcome/Subscribe/Visiting a Courtroom/About moved
  into the footer so nothing became unreachable. Root CSS color tokens
  (`--navy`/`--paper`/`--accent`) were updated site-wide to the approved
  design's exact values -- a refinement of the existing palette, not a
  second one. "This Week's Pick" reuses the existing Editor-curated
  `curated_blurb` field (soonest upcoming hearing with one, falling back
  to soonest overall) rather than adding a new "featured" flag.
- **Justice-only availability meter** (`app/availability.py`, new): each
  Justice records recurring weekly free-time blocks
  (`AdminUser.availability_blocks`, JSON-encoded, same
  `{day_of_week, start_time, end_time}` shape used everywhere below) via
  `GET`/`PATCH /api/justices/me/availability` -- a dedicated endpoint/
  schema, deliberately never folded into the public `JusticeOut` shape a
  Justice's profile is otherwise built from. `POST /api/hearings/
  availability-summary` (Justice-gated via `require_justice`, batched
  over the exact hearing IDs the caller already has) returns a per-
  hearing free-Justice count/list, rendered as a red-to-green bar
  (`AvailabilityMeter.jsx`) -- not a badge, a different shape entirely so
  it can't be confused with the other two hearing-card indicators below.
  Completely absent from the DOM and from any network request for a
  non-Justice viewer.
- **Public availability matching** (`frontend/src/availabilityMatch.js`,
  `useVisitorAvailability.js`, `AvailabilityPanel.jsx`, all new): a
  visitor can enter the same kind of weekly free-time blocks with no
  login, stored in `localStorage` only (`cusg_visitor_availability`,
  `cusg_visitor_availability_enabled`) unless they explicitly subscribe.
  A "Fits your schedule" badge (outlined teal, `.badge-fits-schedule`)
  appears on matching rows when toggled on -- additive, never filters the
  list. `availabilityMatch.js` is a deliberate line-for-line JS mirror of
  `app/availability.py`'s time-parsing/overlap logic (the two can't
  literally share code across the language boundary), each side
  commented with a pointer to its counterpart.
- **Newsletter opt-in matched to schedule**: `Subscription` gained a
  `personal_availability` filter type and an `availability_blocks`
  column (same JSON shape). `Subscribe.jsx` prefills the block editor
  from the visitor's own `localStorage` availability if they already set
  one. The weekly digest job's per-subscriber dispatch
  (`app/jobs/digest.py::hearings_matching_subscription`) gained a branch
  for it, importing the *same* `hearing_matches_blocks` function the
  meter endpoint uses, so the digest and the meter can never disagree
  with each other.
- **Three hearing-card indicators, kept visually distinct**: the existing
  Justice-recommendation star (solid amber `.badge-news` pill, unchanged)
  vs. the Justice-only meter (a bar, not a pill) vs. the new "fits your
  schedule" badge (outlined teal, outside the site's red/amber/navy
  spectrum) -- verified together on real rows carrying all three at once.

## Phase 8 additions (news tracking system rebuild)

A sixth follow-up document: the Phase 6 fuzzy-matching pipeline (polling
~6 RSS/WordPress feeds, then scoring every article against every
hearing) was fragile -- five independent scrapers that could each
silently break -- and still noisy even after Phase 6's own fixes. This
phase inverts the architecture entirely: instead of classifying an
anonymous firehose of articles, it actively searches for news about
each specific upcoming hearing that's already known (case number, party
names). Searching for a known case is a fundamentally easier, higher-
precision problem than classifying an anonymous article -- and one
search mechanism instead of five scrapers directly means fewer
independent failure points. As with Phase 6, this followed the doc's
own diagnosis-first instruction against real data before writing new
logic: the DA-press-release RSS the doc assumed existed doesn't (checked
the real Boulder County DA site directly -- static PDFs on a manually
maintained archive, no feed), and a proposed hard "one row per hearing"
database constraint would have silently orphaned two real, human-linked
duplicate articles already in production (checked directly before
deciding against it).

- **Old pipeline deleted outright**: `app/jobs/news_monitor.py`,
  `app/jobs/news_matching.py`, and their scripts/tests are gone -- no
  fuzzy name/date scoring, no RSS feed list (`NEWS_SOURCES`), no
  confidence tiers left to reason about.
- **New search job**, `app/jobs/news_search.py`, queries the Google
  Custom Search JSON API once per eligible hearing (Jury Trial/Oral
  Argument, not cancelled, not excluded). A case number found in a
  result is a deterministic Tier 1 auto-match
  (`MatchStatus.auto_matched`); anything else becomes a Tier 2 "weekly
  reading list" item (`MatchStatus.in_weekly_reading_list`) for a
  curator to confirm or dismiss. A result on `bouldercounty.gov` is
  tagged `SourceType.da_press_release` regardless of tier.
- **Cadence, not a firehose poll**: two nullable `Hearing` timestamps
  (`news_search_initial_at`, `news_search_prehearing_at`) drive one
  daily job doing two passes -- every hearing gets one initial search
  the first time it's eligible (self-healing on deploy day), and
  anything still unresolved gets re-searched once within
  `NEWS_SEARCH_PREHEARING_WINDOW_DAYS` (default 5) of its date. A
  resolved hearing (`auto_matched`/`manually_linked`/`dismissed`) is
  never re-searched, which is also most of what keeps daily query volume
  low (~10-60/day at this project's real scale, against a 100/day free
  quota).
- **Soft dedup, not a database constraint**: `NewsMention.article_url`
  is no longer globally unique, and there's deliberately no uniqueness
  constraint on `hearing_id` either -- checked production directly and
  found 8 hearings already carrying more than one `NewsMention` row,
  including 2 with a human-confirmed second real link. The job's own
  "check for an existing row before creating one" logic is what stops
  automated duplicates going forward; it never forces existing or future
  manual links to collapse.
- **Quota tracking + real alerting**: a new `ExternalApiUsage` table
  (`app/external_api_usage.py`) counts queries per API per day and fires
  an email alert once (`alert_sent_at` gates it) when usage crosses
  `SEARCH_API_ALERT_THRESHOLD` (default 90/100). `app/alerting.py` grew
  a real `ALERT_BACKEND=email` path that reuses the existing SendGrid-
  backed `send_email()` from `app/jobs/digest.py` rather than a new
  integration -- console-only alerting was silent by construction, which
  defeated the entire point of a quota-warning ask.
- **A real, unrelated bug found and fixed along the way**: the weekly
  digest's GitHub Actions job (`.github/workflows/scheduled-jobs.yml`)
  only ever set `DATABASE_URL`, never `EMAIL_BACKEND`/`SENDGRID_API_KEY`
  -- meaning it had almost certainly been silently falling back to
  console-only logging instead of actually emailing subscribers every
  Monday since that job was added. Fixed in the same pass since it's the
  same file and the same root cause (a job's env-var block never set up
  for real email delivery).
- **A second real bug caught in this phase's own manual verification**:
  `GET /api/hearings/{id}` 500'd on any hearing with a news mention,
  because `NewsMentionOut.hearing` reads the ORM `NewsMention.hearing`
  relationship (a raw `Hearing` object), and pydantic v2 doesn't
  propagate `from_attributes=True` into a nested submodel's own
  validation just because the outer model has it --
  `NewsMentionHearingSummaryOut` needed the same config itself. Caught
  by hitting the real endpoint locally with seeded data, not by the test
  suite (which only ever built that schema by hand with plain values,
  never round-tripped through the ORM relationship) -- fixed, and a
  regression test added (`test_news_review_queue.py`) that exercises the
  real endpoint end to end.
- **`HearingOut.news_mentions` filter fix**: a `field_validator` mirrors
  the existing `community_submissions` one, filtering the embedded list
  down to confirmed statuses (`auto_matched`/`manually_linked`) before
  it reaches JSON -- fixing a pre-existing bug where `HearingList.jsx`/
  `HearingDetail.jsx` checked the raw array length instead of the
  backend's own confirmed-only definition, with zero frontend changes
  needed to fix it.
- **Admin UI rebuilt around one queue, not a diagnosis dashboard**: the
  News tab is now a single "Weekly reading list" (headline, source,
  source-type badge, the linked hearing's case number/date/parties,
  Confirm relevant/Dismiss) plus a collapsed read-only "Recent
  auto-matched" section for transparency -- no case-number input, no
  backfill button, since a deterministic model has no ambiguity or stale
  logic left to re-run.

## Phase 9 additions (the "Learn" teaching feature)

A seventh follow-up document: give a visitor who doesn't understand what
kind of hearing they're looking at a way to learn, and give Justices a
place to practice teaching what they know. Two distinct content types,
kept structurally and visually separate per the doc's own explicit
instruction, since one is reusable and one is a one-off:

- **`LearnTopic`** (`app/learn.py`, `app/routers/learn.py`): a reusable
  explainer a Justice writes once, matched to hearings by
  `hearing_type_category`/`case_category` -- not a stored relationship,
  since the match is a lookup, not a per-hearing attachment (see
  `app/learn.py::matching_learn_topics`). An unset dimension on a topic
  means "matches any value" for that dimension, not "matches nothing" --
  a type-only topic (e.g. "What is a Jury Trial") matches every hearing
  of that type regardless of case category, and a hearing can match more
  than one topic at once (a type-based one and a category-based one
  both applying). At least one dimension must be set, enforced in the
  router, not the DB. Publicly browsable at `/learn`, filterable the
  same way `/archive` already is.
- **`CaseTeachingNote`** (real FK to one `Hearing`, unlike `LearnTopic`):
  an optional, one-off note for something unusual enough about one
  specific case to be worth explaining beyond the general topic --
  managed inline on that hearing's own detail page (matching how
  Recommendations already attach to one `Hearing` there), not through
  the admin dashboard.
- **Role check reused, not reinvented**: every mutating endpoint uses
  `require_editor` -- the doc's own explicit phrase was "the existing
  Editor/admin role," and every real Justice account already has
  `role=editor` by construction (Phase-3 doc, Section 2's merge
  decision), so this is "Justices only" in effect without adding a third
  role dependency alongside `require_editor`/`require_justice`.
- **Video: paste a URL (the reliable path) or upload a short file
  directly (a convenience, not the main path).** A pasted YouTube/Vimeo
  URL renders as an iframe embed; anything else (a direct file link, or
  an uploaded file) renders as a native `<video>` tag -- see
  `frontend/src/components/VideoEmbed.jsx`. An uploaded file reuses
  `AdminUser.photo_data`'s exact storage convention (Postgres BYTEA,
  served via a dedicated `GET .../video` endpoint). Real, deliberate
  departure from the photo path, though: no re-encoding (Pillow can't
  decode video, no ffmpeg dependency here), and a cap that took two
  passes to get right -- raised from an initial 15MB (too tight to fit
  more than a 15-20 second clip) to 100MB on request, then a real
  ~1.5-minute upload failed live in production with a bare "Failed to
  fetch" -- no HTTP response at all, not this module's own clean "file
  too large" error. That means Render's free-tier proxy killed the
  connection (almost certainly a request-duration timeout on a slow
  upload, since Render doesn't publish a body-size limit) before it
  reached the app at all -- confirmed not a bug in the handler itself (a
  40MB upload against a local copy of the exact same backend completed
  in under a second). Lowered to 25MB as a conservative, *unverified*
  guess at a size likely to transfer within whatever that real limit is
  -- not measured against production directly (no admin credentials
  available to test the live deployment with). Given this, pasting a
  URL is the actually-reliable path for anything resembling the "few
  minutes" this feature is meant for; direct upload only really suits a
  short clip, and the UI says so. See `app/video_upload.py`'s docstring
  for the full account. If direct upload for real-length video ever
  needs to work reliably, the fix is a real object-storage service with
  chunked/resumable upload, not a bigger number here.
- **A real bug caught only by asking "will it actually play?"**: the
  Phase-4 doc's Content-Security-Policy (`frontend/vercel.json`) had no
  `frame-src` or `media-src` directive, so both silently fell back to
  `default-src 'self'` -- meaning every video path this feature adds
  (a YouTube/Vimeo iframe, a direct-file `<video>`, and even an uploaded
  video served from our own API, a *different* origin than the frontend)
  was blocked by the browser in production from the moment this phase
  shipped, with no visible error anywhere in this app's own code or
  logs -- confirmed by reading the live CSP header directly, not
  guessed. Should have been checked when `VideoEmbed.jsx` was built, not
  after. Fixed by adding `frame-src https://www.youtube.com
  https://player.vimeo.com` (the only two origins our own embed code
  ever generates) and `media-src 'self' https://cusg-court-tracker-api.onrender.com https:`
  (the last, broader `https:` specifically to allow an editor-pasted
  direct-file link hosted anywhere -- an intentional, small relaxation,
  scoped to media playback only and to content only a trusted, `require_editor`-gated
  Justice can set, not arbitrary public input).
- **"Copy to Archive" reuses the real Archive creation path**, not a
  hand-rolled duplicate: `routers/learn.py::copy_teaching_note_to_archive`
  calls `routers/archive.py::create_archive_entry` directly, so it
  inherits that endpoint's own business rules for free (the
  hearing-must-have-already-happened check correctly 400s a note tied to
  a future hearing) rather than re-implementing them. Copies the note's
  content into a new `ArchiveEntry`; the original `CaseTeachingNote` is
  untouched afterward. `judge_name` is filled from the hearing's own
  known value when set (real data, not a guess); `attendees` has no
  equivalent on a teaching note and is left for the Justice to fill in
  on the new Archive entry directly.
- **A real crash caught before it shipped**: the first working version
  had `GET /api/hearings/{id}` embedding `teaching_notes` via the exact
  same `field_validator`-flattening pattern `_flatten_attendance` uses
  for `HearingAttendance` -- necessary because `CaseTeachingNoteOut`'s
  `created_by_display_name` has no identically-named ORM attribute for
  `from_attributes` to auto-populate from (only a `.created_by`
  relationship object), the same class of gap the Phase 8 round already
  found and fixed for `NewsMentionOut.hearing`. Caught this time by
  writing the flattening validator up front, from that precedent,
  instead of after a crash.
- **Both new hearing-card/detail-page indicators are visually distinct
  from every existing one and from each other**: solid indigo
  (`badge-learn-topic`) for the general, reusable match vs. an outlined
  plum (`badge-teaching-note`) for the one-off, case-specific note --
  neither hue overlaps the existing amber/navy/tan/grey/teal palette.
  The visual key (`HearingCardKey.jsx`) explains both.

## Phase 10 additions (page redesign + "This Week's Pick" / pinned recommendation)

A design-mockup build prompt asked for a visual redesign of four
already-existing, already-wired pages (Home, Recommendations, Archive,
Learn) into a warmer, more editorial look, with a shared design-system
token set. All four already pulled from real data -- this was layout/
styling work, not new-feature work, **except** for one real gap the
mockup assumed away: it described a homepage "This Week's Pick" and a
Recommendations "Lead Recommendation" as if a real "currently featured"
flag already existed. It didn't -- Home.jsx used a client-side heuristic
(soonest hearing with a `curated_blurb`), and Recommendations.jsx was a
flat list with no concept of one being "the lead." Confirmed with the
user: build both as real features, then redesign on top of them.

- **`Hearing.is_weekly_pick`** and **`HearingRecommendation.is_pinned`**:
  new boolean columns on existing tables (migration entries needed, per
  this project's established convention). Both are "exactly one row
  True at a time" *by construction*, not a DB constraint -- setting one
  clears every other row of that type in the same transaction
  (`routers/admin.py::set_weekly_pick`, `routers/justices.py::
  pin_recommendation`), the same soft-enforcement spirit as this
  project's other single-current-thing invariants (e.g. Phase 8's
  soft-deduped `NewsMention`). Toggled inline on the pages that already
  show the underlying content -- a "Set/Remove as This Week's Pick"
  button on the hearing detail page (`require_editor`, next to where
  blurb/exclusion controls already live conceptually) and "Pin as lead"/
  "Unpin" buttons on the Recommendations page (`require_justice`,
  same peer-to-peer gate as create/delete recommendation right next to
  it) -- not a new admin-dashboard tab. Home.jsx's spotlight falls back
  to the old heuristic when nothing's been explicitly picked yet, so it
  never goes empty.
- **Design tokens**: the mockup's palette mapped almost exactly onto
  tokens that already existed (`--navy`, `--paper`, `--accent`, `--line`
  were all exact or near-exact matches -- confirmed by reading the
  actual hex values before adding anything new, per the mockup's own
  "map rather than duplicate" instruction). Only genuinely new: four
  Archive-only accent colors (`--terracotta`, `--sage`, `--ochre`,
  `--plum`) and `--font-mono` (IBM Plex Mono, for Learn's numbered
  entries). The nav bar's dark-navy Phase-6.2 look became a light cream
  header with the current page in amber/bold and "Justice Sign In" as a
  bordered pill -- a restyle, not a re-architecture, since the actual
  links/order (Calendar/Recommendations/Archive/Learn/Meet the Justices)
  were already right from Phase 9.
- **Icons**: no icon library anywhere in this codebase, and one existing
  precedent -- `ColonnadeMotif.jsx`, a hand-authored inline SVG that
  already exactly matched the mockup's "faint decorative colonnade, ~6%
  opacity" homepage request (it already existed at 8% opacity) and got
  reused as-is. New icons (a hearing-type glyph for Learn's sidebar)
  followed the same hand-authored-inline-SVG convention rather than
  adding a dependency.
- **Archive's rotation/color-cycling is computed, not stored**:
  `Archive.jsx` derives each entry's accent color (round-robin over the
  four Archive tokens, so no two consecutive entries share one) and
  alternating card rotation from its position in the list, not from any
  new database field -- purely presentational, reflows correctly no
  matter how many real entries exist.
- **Learn gained a real detail page** (`/learn/:id`,
  `LearnTopicDetail.jsx`): the redesigned grid card now shows a short
  excerpt with a "Read the full guide" link, per the mockup -- the full
  `body_text`/video/external-links content that used to render inline
  on the grid itself moved to this new page. `api.getLearnTopic`
  (already existed) is what it calls.
- **Archive pagination**: the mockup asked for "paginated or infinite-
  scrolled." No backend pagination endpoint existed (`GET /api/archive`
  has no limit/offset params) and adding one was out of scope for a
  visual redesign, so this is a client-side "Show more" reveal over the
  already-fetched, already-sorted (`created_at.desc()`) list rather than
  a new API parameter.

## Phase 11 additions (month calendar view + clickable hearing tags)

A build prompt added a month-grid view (behind a List/Month toggle,
List stays default) to the existing Calendar page, plus made every
hearing-type tag sitewide clickable, linking to that specific hearing.
Two real gaps surfaced during review and were resolved directly with
the user before building:

- **The doc assumed a rich per-type color palette already existed.** It
  didn't -- every hearing-type tag sitewide used one single gray
  (`.badge-category`), and the real data model only cleanly distinguishes
  two types (`HearingTypeCategory.jury_trial`/`oral_argument_motions`);
  everything else the doc named (sentencing, arraignment, motions) was
  either bucketed into `other` or is a `ProceedingStage` value that only
  ever exists on *Archive* entries, never on an upcoming `Hearing`. User
  chose to build a real finer-grained mapping rather than fake one with
  only 2-3 real colors.
- **The month view's "day availability" bar didn't map onto the existing
  per-hearing system**, which needs a specific date+time+duration, not
  just a date. User chose: average free-Justice fraction across that
  day's slots. Investigating this turned up a real simplification:
  Justice availability is recurring *weekly* (`AvailabilitySlot.
  day_of_week`, never tied to a calendar date), and `GET /api/justices/
  team/availability` already returns every (weekday, slot) cell's
  free-count in one call -- a calendar date's availability is just
  whatever its weekday's already-fetched recurring profile says, so
  **no new backend endpoint was needed** for this at all, just
  client-side aggregation over data `TeamAvailability.jsx` already pulls.

**Finer-grained tag colors** (`app/hearing_types.py`): extended, not
duplicated -- its `_RULES` list already had ~30 real, battle-tested
patterns mapping raw docket hearing-type strings to a category and a
plain-language description; each tuple gained a 4th element, a
`tag_color` group key, grouped from what each rule's own existing
display text already says the hearing *is* (8 groups: `jury_trial`,
`oral_argument`, `trial`, `sentencing`, `arraignment`, `scheduling`,
`family_probate`, `other`). Stored on `Hearing.tag_color` (new column,
computed once at docket-pull time exactly like the pre-existing
`hearing_type_display`/`hearing_type_category` columns right next to
it -- not recomputed on every read) and self-heals for already-ingested
hearings within one daily pull cycle, same reasoning as every other
additive column this project has shipped, since `docket_pull.py`
already overwrites those two sibling fields on every row it re-sees.
Exposed on `HearingOut` directly, and as `hearing_tag_color` on
`RecommendationOut`/`ArchiveEntryOut` (the two schemas that embed a
hearing's type as plain text without the full `Hearing` row).

**Clickable tags** (`components/HearingTypeTag.jsx`): a shared component
replacing every ad-hoc inline tag/badge for a hearing's type across
Home, the Calendar (list rows and the new month-view chips),
Recommendations (lead card + grid), and Archive. Links to that specific
hearing with `stopPropagation()` so it never fights a surrounding card's
own click handling; renders as plain non-clickable text when no
`hearingId` is in scope. One real HTML-correctness catch along the way:
the Calendar list view's whole row is already one big `<Link>` to the
same hearing, so nesting another `<a>` inside it for the tag would be
invalid HTML for zero navigational benefit -- that one call site renders
the tag colored but non-clickable instead, losing nothing (the row
already goes to the same place).

**Month calendar view** (`components/MonthCalendar.jsx`, toggled from
`HearingList.jsx` via `?view=month`, not a separate route): fetches only
the viewed month's hearings by reusing `GET /api/hearings`'s existing
`date_from`/`date_to` params -- no new backend route needed here either.
Six-row grid including grayed adjacent-month days (not fetched, per the
doc's own "refetch only this month's data"), up to 3 colored tag chips
per day plus a "+N more," today marked with a filled amber circle,
every day cell keyboard-operable. Selecting a day drives a sidebar
(that day's hearings in the same row style Home.jsx's "Get Started"
list already uses, a "View full day on the docket" deep link back to
List view via `?view=list&date_from=X&date_to=X` -- which required
`HearingList.jsx` to start honoring an initial date range from the URL,
a small addition alongside the `view`/`month` param plumbing it didn't
have before -- the Justice-only availability gauge, and a color legend
satisfying the doc's own "color alone isn't enough" accessibility note).
The availability gauge is a static red-to-green bar with one marker at
the day's averaged free-fraction (not a per-time-of-day timeline), per
the user's chosen aggregation approach, reusing the exact hue-sweep
formula `AvailabilityMeter.jsx` already uses elsewhere.

### Phase 11 follow-up: fixing crowding on a busy day

The first pass above used full-text tag chips stacked inside each day
cell. Real feedback on a busy week: two or three hearings and the cell
is already fighting for space, and a genuinely heavy day (Boulder
arraignment/traffic dockets can run into the hundreds in one session)
would overflow badly. Two real fixes, both frontend-only:

- **The grid now shows dots, not chips** -- one small solid-colored
  circle per hearing (same 8 `tag_color` hues, just solid instead of the
  pill's soft-background-plus-text), capped at 3 dots plus a `+N`
  overflow indicator (`"99+"` past 99, so the badge never needs to grow
  to fit a three-digit count). No label text in the cell at all -- the
  grid's job is to show *where* things are busy, the sidebar explains
  *what*. A dot is still a real link straight to that hearing (same
  `stopPropagation` as the tag it replaces) with a `title`/`aria-label`
  carrying the hearing's type and time, covering "a lightweight tooltip
  ... for anyone who wants a peek" without a custom tooltip-state
  machine -- `title` covers hover on desktop and long-press on most
  mobile browsers.
- **The sidebar gained a high-volume mode** (`MonthCalendar.jsx::
  HighVolumeDaySummary`, triggered past `HIGH_VOLUME_THRESHOLD = 20`
  hearings in one day): a flat list of 140 hearings is "just as
  overwhelming as the crowded grid was, only pushed one click deeper."
  Past that threshold, the sidebar leads with grouped counts by
  `tag_color`, a "Notable" section (any hearing that day already
  flagged elsewhere -- a Justice recommendation, via the same
  `GET /api/recommendations` call `Home.jsx`/`HearingList.jsx` already
  make, or confirmed news coverage, already embedded on every
  `HearingOut`), and a client-side search over case number/courtroom/
  type. Deliberately never renders the full row-by-row list inline no
  matter how someone filters, even a search match -- past a small
  display cap it points at the existing "View full day on the docket"
  link into List view, where real pagination already makes sense. No
  backend changes needed for any of this; everything was already either
  on the hearing objects already being fetched or one additional call to
  an endpoint that already existed.

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
