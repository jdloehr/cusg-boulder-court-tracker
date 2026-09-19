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
6. Back on Render (the backend service) -> **Environment** -> add
   `FRONTEND_URL` = this Vercel URL (no trailing slash). Phase 3's
   invite-link and password-reset emails build their links as
   `{FRONTEND_URL}/accept-invite/{token}` etc. -- without this set, those
   links come out as bare relative paths (`/accept-invite/...`, no
   domain), which still work if pasted directly into a browser already on
   the site but aren't a real clickable link in an email. Redeploy the
   backend after adding it (Render env var changes need a redeploy to
   take effect).

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

## Schema changes: no Shell access on this Render plan

Discovered the hard way during the Phase-2 round: this backend service's
Render plan does **not** include the Shell tab (it's a paid-plan
feature), so there's no way to log into the running container and run a
one-off script by hand -- the "open the Shell tab and run
`scripts/check_enum_drift.py`" instructions from earlier in this build
don't work here.

Two different consequences follow from that:

**Schema patches that need to actually change the database (new columns
on an existing table, a new enum type an existing table's column needs)
now run automatically on every backend startup** -- see
`app/migrations.py`. Nothing to do by hand on deploy; this exists
*because* Shell isn't available, not in spite of it. If a future change
needs a genuinely manual, one-time data fix (backfilling a value from
external data, say -- not just "make a column exist"), the only way to
run it without Shell access is locally against the real database (below).

**Read-only diagnostics** (`scripts/check_enum_drift.py`,
`scripts/add_livestream_columns.py` -- kept for reference/local use even
though the column migration itself is now automatic) still need to be
run from somewhere with the production `DATABASE_URL`. Without Shell
access, that means running them from your own machine, using the
Postgres database's **External Database URL** -- this is a property of
the Postgres resource itself (dashboard -> your database -> **Info**
tab), not the web service, so it's available regardless of the web
service's plan:

```bash
cd backend
DATABASE_URL=<Render Postgres External Database URL> python scripts/check_enum_drift.py
```

## 5. Real email delivery (optional -- invite links, password resets, the digest)

Without this, everything still works -- invite/reset links are logged
(Render's dashboard -> your service -> **Logs**) and also handed back
directly in the API response (the admin dashboard's "Invite a Justice"
tab shows the link right after you create one), so you can always copy/
paste it by hand. This section is for making that automatic.

Using [SendGrid](https://sendgrid.com) here since its free tier (100
emails/day, forever, no credit card) needs only a single verified sender
address -- not a whole custom domain -- which fits a project running on
a bare `.vercel.app`/`.onrender.com` URL. Resend, Postmark, etc. would
also work but expect a verified domain for real use.

1. Create a free SendGrid account.
2. **Settings -> Sender Authentication -> Verify a Single Sender.** Use
   an email address you can actually receive mail at (your own, or a
   CUSG address) -- SendGrid sends a confirmation link there and refuses
   to send *from* this address until you click it.
3. **Settings -> API Keys -> Create API Key** (Restricted Access is fine
   -- it only needs "Mail Send" permission). Copy the key now; SendGrid
   only shows it once.
4. Render dashboard -> your backend service -> **Environment** -> add:
   - `EMAIL_BACKEND` = `sendgrid`
   - `SENDGRID_API_KEY` = the key from step 3
   - `EMAIL_FROM_ADDRESS` = the address you verified in step 2
   - `EMAIL_FROM_NAME` = `CUSG Boulder Court Tracker` (or whatever you'd
     like recipients to see)
5. Redeploy (env var changes need one). Test it by creating a real
   invite from the dashboard for an email address you can check --
   the link should now actually arrive, not just appear on-screen.

A failed send (bad key, unverified sender, SendGrid briefly down) never
breaks the feature that triggered it -- it's logged loudly
(`app/jobs/digest.py::_send_via_sendgrid`) and the app moves on; an
invite's link is still shown directly in the response either way.

## 7. Phase 4: production hardening flags to set on Render

Add these to the backend service's **Environment** tab (same place as
`FRONTEND_URL`/`SENDGRID_API_KEY`):

- `ENVIRONMENT` = `production` -- disables the interactive API docs
  (`/docs`, `/redoc`); real attack-surface reduction now that this is
  linked from an official page, and no external integrator needs them.
- `ALLOWED_ORIGINS` = your real frontend URL(s), comma-separated, if it's
  ever anything other than the default baked into `app/config.py`
  (`https://cusg-boulder-court-tracker.vercel.app` plus localhost) -- e.g.
  once a custom domain exists, add it here too or the browser will block
  the frontend's own API calls with a CORS error.

Redeploy after adding either (env var changes need one, same as every
other setting here).

### Updating a Justice's login email

`JUSTICE_EMAIL_UPDATES` -- a JSON object mapping each account's *current*
email to its new one, e.g.:
```
{"dillon.rankin@cusg-justices.local": "real.address@colorado.edu"}
```
Applied automatically at every startup (`app/account_email_updates.py`)
and safe to leave set indefinitely -- once an account's email has
actually changed, the old address in the mapping no longer matches
anything, so it becomes a silent no-op on every boot after that. The
account itself (password, role, profile, attendance/recommendation
history) is untouched; only the login address changes. If whoever's
switching to the new address doesn't know the account's existing
password, "Forgot your password?" on the sign-in page now works for the
new address, same as it would for any account.

Deliberately an env var, not something typed into a script or committed
to this repo: real people's real email addresses shouldn't end up in
this public repository's source or git history.

## 8. Email authentication (SPF/DKIM/DMARC) -- once a real sending domain exists

Only relevant once `EMAIL_FROM_ADDRESS` (Section 5) is on a domain you
actually control DNS for -- SendGrid's own shared sending domain (the
default if you verify a Single Sender on, say, a personal Gmail address)
doesn't give you DNS records to add at all, so this step is genuinely
blocked until CUSG has its own domain to send from. Once one exists:

1. SendGrid dashboard -> **Settings -> Sender Authentication -> Authenticate
   Your Domain** -- walks through adding CNAME records (this is what
   actually sets up SPF and DKIM alignment for that domain) at whatever
   registrar hosts the domain's DNS.
2. DMARC is a separate TXT record (`_dmarc.yourdomain.com`) you add
   yourself -- SendGrid's docs have exact syntax; start with a
   monitor-only policy (`p=none`) and tighten it once you've confirmed
   mail is landing correctly.

Without this, mail still sends (via SendGrid's own shared infrastructure,
which has its own baseline reputation/authentication) -- this step is
about *this project's* domain being able to authenticate its own mail,
not a requirement for email to work at all.

## 9. Worth checking before the link goes live on the official CUSG site

Not a technical step -- flagged because it depends on CU's own internal
policy, not something to guess at in a build spec: check whether CU
Boulder's IT department or CUSG's advisor has an existing security/
compliance review process for student-built tools being linked from an
official page. If one exists, this document (plus `docs/SECURITY_
REVIEW.md`) is a reasonable starting point to bring to that review, but
isn't a substitute for it.

## 10. What's still manual after this
- **A CUSG custom domain**, if you want one, is a DNS change plus adding
  it in the Vercel (and optionally Render) project settings -- not
  something I can do without access to CUSG's domain registrar. Also
  update `ALLOWED_ORIGINS` (Section 7) once you have one.
- **Render's free Postgres** is fine to start, but check Render's current
  free-tier database retention policy before relying on it long-term (this
  has changed over time across providers); upgrading to a paid instance
  later is a dashboard setting, not a code change.
