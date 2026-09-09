# CUSG Boulder Court Tracker

A tool for the **CUSG Supreme Court** (and pre-law students more broadly)
to find upcoming, in-person Boulder-area court proceedings worth sitting in
on -- jury trials, oral arguments, and motions hearings -- planned at least
a week or two out, plus anything getting real local news coverage. Full
spec in the original build prompt; this README covers what was actually
built and how to run it.

Beyond the original spec: anyone can RSVP a Justice's attendance to a
hearing (no login) and recommend hearings on a shared board with an email
alert option; any visitor can propose case details (a summary, a judge's
name) for the team to review; the feed now also covers the Colorado
Supreme Court and Court of Appeals, restricted to cases already
newsworthy or likely to become so; and a first-visit welcome page
explains how to use the tool.

**This was built and validated against real, live data, not mocks.**
During this build the docket-pull job pulled real Boulder County court
data (~5,000 hearings across a rolling 28-day window), the news-monitoring
job pulled real articles from six live Boulder-area and statewide sources,
and the federal supplement uses a real, currently-scheduled U.S. Supreme
Court case (confirmed directly against supremecourt.gov). See
[`docs/DATA_SOURCE_FINDINGS.md`](docs/DATA_SOURCE_FINDINGS.md) for the full
account, including several real bugs that only showed up against live data
and how they were fixed.

## What's real vs. stubbed

| Piece | Status |
|---|---|
| Docket-pull pipeline (fetch, decode, classify, filter, diff/upsert) | **Real, working, tested against live data.** |
| News-monitoring pipeline (6 real sources, extraction, matching, review queue) | **Real, working, tested against live sources** -- 4 Boulder-specific (Boulder Reporting Lab, Daily Camera, CU Independent, Boulder Weekly) + 2 statewide supplementary. No naturally-occurring auto-match happened to occur during build (see findings doc for why that's an honest data fact, not a bug); the auto-match code path itself is tested against clearly-labeled synthetic fixtures. |
| Appellate supplement (CourtListener search: federal + Colorado Supreme Court/Court of Appeals) | **Real, working**, seeded with one real, currently-scheduled federal case; "In the news" curation hint verified live against real Colorado Supreme Court search results. |
| Public list/detail/subscribe/recommendations/welcome views | **Real, working**, React frontend against the real API. |
| Admin/curation tool (review queues, blurbs, exclusion, academic calendar, activity log) | **Real, working.** |
| CUSG Justice features (attendance RSVP, recommendation board) | **Real, working**, seeded with the actual 7 Justices, no login required (by request) -- verified end-to-end as a fully anonymous visitor. Not in the original spec -- added on request. |
| Public "add case details" submissions | **Real, working**, moderated by an Editor before anything publishes. Not in the original spec -- added on request. |
| Email alert on new recommendations | **Real, working** (console-logged, same as the weekly digest -- see Email delivery below). Not in the original spec -- added on request. |
| Academic-calendar de-emphasis | **Real, working**, seeded with CU Boulder's actual published Fall 2026 dates. |
| Email delivery | **Stubbed to console/log output.** No transactional-email account exists for this build; the digest-selection and suppression logic is fully implemented and testable, only the "send" call is a stand-in. See `app/jobs/digest.py`. |
| Job-failure alerting | **Stubbed to console/log output**, same reasoning. See `app/alerting.py`. |
| Hosting / Postgres / real cron | **Not deployed** -- this build ran locally with SQLite. `DATABASE_URL` switches to Postgres with no code change; see `docs/ARCHITECTURE.md`. |

## Quickstart

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Pull real live data, seed demo curation accounts + academic calendar +
# one real federal case + one curated blurb. Safe to re-run.
python scripts/seed_demo_data.py

# Create the 7 real CUSG Justice accounts (random passwords, printed once
# to stdout -- see the script's docstring, and save them somewhere private).
python scripts/create_justices.py

uvicorn app.main:app --reload   # http://localhost:8000
```

Demo curation logins (created by the seed script, for the Editor/
Contributor tooling): `editor@cusg-demo.colorado.edu` / `changeme` (Editor)
and `contributor@cusg-demo.colorado.edu` / `changeme` (Contributor). Change
these before any real deployment. Justice logins come from whatever
`create_justices.py` printed when you ran it.

Run the test suite (55 tests, well under 30s, no network needed except one
live CourtListener integration test that skips gracefully if offline):

```bash
pytest
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, talks to the backend at localhost:8000
```

### Re-pulling data manually

```bash
python scripts/run_docket_pull.py     # state docket export, daily in production
python scripts/run_news_monitor.py    # news sources, daily in production
python scripts/verify_data_sources.py # re-checks court codes, appearance-type
                                       # distribution, and news-source reachability --
                                       # see docs/DATA_SOURCE_FINDINGS.md
```

In production these run on a schedule via `app/jobs/scheduler.py`
(`ENABLE_SCHEDULER=1`) or your host's own cron/scheduled-function feature.

## Documentation

- [`docs/DATA_SOURCE_FINDINGS.md`](docs/DATA_SOURCE_FINDINGS.md) -- what
  was confirmed live, what broke and was fixed against real data, and the
  Section 10 open questions resolved during build.
- [`docs/CASE_CATEGORY_DECODING.md`](docs/CASE_CATEGORY_DECODING.md) --
  the case-number and hearing-type decode tables, and how to extend them.
- [`docs/EXCLUSION_LOGIC.md`](docs/EXCLUSION_LOGIC.md) -- exactly how
  juvenile and sensitive cases (and visitor-submitted content) are, and
  aren't, filtered.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) -- repo layout, schema
  deltas from the original spec and why (including the post-spec Justice
  and community-submission features), known limitations, next steps.
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) -- step-by-step real
  deployment: GitHub + Render (backend/Postgres) + Vercel (frontend) +
  free scheduled jobs via GitHub Actions.

## Design

Civic/legal-reference look per the build prompt's Section 3: serif
headings (Source Serif 4), sans body/tables (IBM Plex Sans), muted
navy/charcoal palette with a single amber accent for calls-to-action and
the "in the news" flag. Screenshots of the running app are the best way to
see it -- run the quickstart above.

## Not done / needs a human

- A real transactional-email account and a real job-failure alerting
  channel (Slack webhook, PagerDuty, etc.) -- both are one small, isolated
  code change away once credentials exist.
- Hosting and a production Postgres instance -- this build ran entirely
  locally.
- A password-reset flow for Justice/curation accounts -- for now, re-run
  the relevant seed script for one person after deleting their row.
- Ongoing hearing-type/case-category coverage maintenance as Colorado's
  courts introduce new raw strings over time -- the admin review queue is
  built for exactly this, but someone on the team needs to actually look
  at it periodically.
