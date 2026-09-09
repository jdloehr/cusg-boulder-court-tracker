# Deployment

Real, permanent hosting: **GitHub** (source of truth both Render and
Vercel deploy from) + **Render** (FastAPI backend + Postgres) +
**Vercel** (React frontend, static). Nothing here can be completed without
you: account creation and OAuth logins need your browser, and I don't have
credentials for any of these services. Everything below is either a
command to run yourself, or a short set of clicks in a dashboard.

## 1. Push the code to GitHub

```bash
cd /Users/josh/cusg-court-tracker
git init
git add -A
git commit -m "Initial commit: CUSG Boulder Court Tracker"
```

Then create an empty repo at [github.com/new](https://github.com/new)
(don't initialize it with a README -- this repo already has one), and:

```bash
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

(If you'd rather I do the git commands above myself once you've created
the empty repo, just give me the repo URL and say go -- I can run `git`
directly, I just can't create the GitHub repo or authenticate for you.)

## 2. Backend + Postgres on Render

1. Create a free account at [render.com](https://render.com) (GitHub login
   is the easiest option -- it also handles connecting the repo).
2. Dashboard -> **New +** -> **Blueprint**. Point it at your GitHub repo.
   Render reads [`render.yaml`](../render.yaml) at the repo root and
   creates both the Postgres database and the web service in one step,
   with `DATABASE_URL` already wired between them.
3. Wait for the first deploy to finish (Render's free web-service tier
   spins down after 15 minutes idle and takes ~30-60s to wake back up on
   the next request -- normal, not a bug).
4. Once it's live, note the service's public URL (something like
   `https://cusg-court-tracker-api.onrender.com`) -- the frontend needs it
   in step 3.
5. Open the service's **Shell** tab (Render dashboard) and run the
   one-time seed commands against the real production database:
   ```bash
   python scripts/seed_demo_data.py     # real docket pull + news pull + academic calendar + federal case
   python scripts/create_justices.py    # the 7 real Justice accounts -- SAVE the printed passwords
   ```
   Consider deleting the two demo curation accounts
   (`editor@cusg-demo.colorado.edu` / `contributor@cusg-demo.colorado.edu`,
   password `changeme`) afterward, or at least changing their passwords --
   there's no self-serve password-reset flow yet (see README's "Not done").

## 3. Frontend on Vercel

1. Create a free account at [vercel.com](https://vercel.com) (GitHub login
   again).
2. **Add New** -> **Project** -> import the same GitHub repo.
3. Vercel auto-detects it's a monorepo; set **Root Directory** to
   `frontend` in the project's configure screen (this is a one-time
   setting, not a file you commit).
4. Add an environment variable before the first deploy:
   `VITE_API_BASE` = the Render backend URL from step 2.4 (no trailing
   slash).
5. Deploy. Vercel gives you a `https://<project>.vercel.app` URL
   immediately; add a custom domain later from the project settings if
   CUSG has one.

## 4. Scheduled jobs (free, via GitHub Actions)

Render's own Cron Jobs feature isn't on the free tier. Instead,
[`.github/workflows/scheduled-jobs.yml`](../.github/workflows/scheduled-jobs.yml)
runs the docket-pull (daily), news-monitor (daily), and weekly-digest jobs
directly against the production Postgres database, on GitHub's free
Actions minutes:

1. Render dashboard -> your Postgres database -> copy the **External
   Database URL** (different from the internal one `render.yaml` wired up
   automatically -- the external one is reachable from outside Render's
   network, which GitHub Actions needs).
2. GitHub repo -> **Settings** -> **Secrets and variables** -> **Actions**
   -> **New repository secret** -> name it `DATABASE_URL`, paste the
   external URL as the value.
3. That's it. The workflow runs on its own schedule from here; to sanity-
   check it immediately rather than waiting for the next scheduled time,
   go to the repo's **Actions** tab -> "Scheduled data pulls" -> **Run
   workflow**.

A useful side effect: a failed run shows up as a red X in the Actions tab,
and GitHub can email you on workflow failures (repo Settings ->
Notifications) -- that's Section 8's "alert an Editor on job failure"
requirement, for free, without standing up Slack/PagerDuty.

## After any future deploy that adds/changes an enum value

Real bug hit during this build (see `docs/ARCHITECTURE.md`'s "Known
limitations"): a new value on a Python enum in `app/models.py` doesn't
retroactively reach an already-created Postgres enum type, and the
symptom is a confusing CORS error in the browser (masking a real 500).
After deploying any change that touches an enum, run this once against
production and fix anything it reports before moving on:

```bash
cd backend
DATABASE_URL=<Render Postgres External Database URL> python scripts/check_enum_drift.py
```

## 5. What's still manual after this

- **Email delivery** is still stubbed to logs (see README) -- the digest
  job runs on schedule and computes exactly who should get what, it just
  doesn't send it anywhere yet. Wiring in a real provider (e.g. Postmark,
  SendGrid, Resend all have usable free tiers) is a change confined to
  `send_email()` in `app/jobs/digest.py`.
- **A CUSG custom domain**, if you want one, is a DNS change plus adding
  it in the Vercel (and optionally Render) project settings -- not
  something I can do without access to CUSG's domain registrar.
- **Render's free Postgres** is fine to start, but check Render's current
  free-tier database retention policy before relying on it long-term (this
  has changed over time across providers); upgrading to a paid instance
  later is a dashboard setting, not a code change.
