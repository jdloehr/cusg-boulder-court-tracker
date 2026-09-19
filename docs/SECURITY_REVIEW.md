# Security Review (Phase 2 doc, Section 6; Phase 3 and 4 addenda below)

## Phase 4 addendum

Prompted by a real change in circumstances, not a routine re-check: the
site is about to be linked from the official CU Boulder CUSG website,
which the Phase-4 doc correctly frames as raising the stakes (more
traffic, implicit official association, more attractive to casual
probing) even though nothing about what the app *does* changed. Where
this lands relative to the Phase 2/3 items below:

- **2FA, upgraded from "worth doing before heavier use" to actually
  built.** The Phase 2 review deferred this given a 7-9 person,
  script-gated roster; Phase 3 kept deferring it even after invite-link
  self-service passwords arrived. Official visibility is the concrete
  trigger that changes the calculus -- see `app/totp.py` and
  `docs/ARCHITECTURE.md`'s Phase 4 section for what got built (real RFC
  6238 TOTP, backup codes, a 428 login step).
- **Account lockout**, new this round: repeated failed logins now lock
  the specific account for 15 minutes regardless of source IP, on top of
  the existing per-IP rate limit. Closes the gap where a slow, IP-rotated
  attempt against one specific account wouldn't have tripped the
  IP-based limit at all.
- **CORS's `allow_origins=["*"]`** -- flagged as a known gap since the
  very first deploy ("public read API; tighten... in production" was
  the code comment, literally since Phase 1) -- is now a real,
  environment-configured allow-list (`ALLOWED_ORIGINS`). This was always
  going to get fixed eventually; official linkage is what made "eventually"
  become "now."
- **Response security headers and a real CSP**, genuinely new: nothing in
  Phase 2/3 set `X-Frame-Options`, HSTS, or a `Content-Security-Policy`
  anywhere. See `app/security_headers.py` (backend) and
  `frontend/vercel.json` (frontend, which needed its own separately-
  reasoned CSP since it's the actual HTML/JS-serving origin).
- **Rate-limiting closed out for real**, not just "the ones we thought of
  so far": `POST /api/subscriptions` and the community "add case details"
  form had no rate limit at all before this round -- a real gap, not a
  hypothetical one, since nothing else about those endpoints would have
  caught abuse.
- **The two items this review still can't do anything about**: SPF/DKIM/
  DMARC records need DNS control over whatever domain sends the mail, and
  a CU IT/CUSG-advisor review process (if one exists) depends on CU's own
  internal policy. Both are flagged as action items for the CUSG team in
  `docs/DEPLOYMENT.md` and `docs/ARCHITECTURE.md` -- genuinely not things
  this codebase can determine or configure on its own.

## Phase 3 addendum

Phase 3 (Justice accounts & public profiles) added real write power a
Justice didn't have before -- a self-chosen password (Phase 2's Justices
only ever had random, script-generated ones) and an editable, publicly
visible profile with a photo upload. What changed here, item by item:

- **Strong passwords**: no longer "there's no self-service flow yet" (see
  the original item below) -- invite-accept and password-reset are the
  first self-service password-setting flows this app has, and both run
  through `app/auth.py::validate_password_strength` (min 10 characters,
  not just letters or just digits). Deliberately simple rather than an
  arbitrary complexity checklist -- see that function's docstring.
- **2FA**: still explicitly deferred, same reasoning as the original
  item below -- the roster is still 7-8 people, and invite-link
  provisioning (new this round) if anything *narrows* who can ever get an
  account, since only an existing Editor/Justice can mint one.
- **Rate-limiting**: extended to `POST /api/admin/login` (10 attempts per
  IP per 10 minutes) and `POST /api/auth/forgot-password` (5 per 10
  minutes) -- the small, known roster of accounts is exactly what a
  brute-force or reset-spam attempt would be aimed at.
- **New credential class: invite/reset tokens.** Same treatment as
  passwords in spirit (never stored as the literal, usable secret) but
  a lighter mechanism is correct here, not bcrypt: `app/auth.py::
  hash_token` uses SHA-256, because these tokens are already
  high-entropy random strings (`secrets.token_urlsafe(32)`), not
  human-chosen secrets an attacker could dictionary-guess -- there's
  nothing for bcrypt's deliberate slowness to defend against here that
  the tokens' own entropy doesn't already cover. Both invite and
  reset tokens are single-use (checked via a `used_at` timestamp) and
  expire (48h / 24h).
- **File upload surface, new this round**: profile photos are the first
  file upload in this app. `app/photo.py` validates by actually decoding
  the file with Pillow (a renamed non-image fails here regardless of its
  declared Content-Type or extension), caps the raw upload at 5MB before
  decoding anything, and re-encodes to a fresh JPEG capped at 800px --
  which is also what strips EXIF/metadata (Pillow's `save()` doesn't
  carry the source's metadata forward unless it's explicitly passed back
  in). No image-hosting/CDN service is involved -- photos are stored as
  bytes directly in Postgres and served from a dedicated endpoint, so
  there's no separate storage-service credential or bucket-permission
  surface to get wrong.
- **XSS on the new free-text profile fields** (`bio`, `year_or_major`,
  `why_care`, `fun_fact`): same defense as the Archive's `reflection_text`
  in the original review below -- React's default escaping, plus
  server-side length caps. Not run through `app/moderation.py`'s spam/
  profanity filter, unlike the Archive's fully-anonymous public input --
  a Justice editing their own profile is an authenticated, identified,
  small-roster action, not the anonymous-abuse surface that filter
  exists for.
- **User enumeration**: `POST /api/auth/forgot-password` always returns
  the same generic response regardless of whether the email matches an
  account -- the roster of 7-8 emails isn't sensitive exactly, but there's
  no reason to let the endpoint confirm or deny membership either.

## Original review (Phase 2 doc, Section 6)

Written when the site gained authenticated write-power (recommendations
trigger emails; attendance is real per-Justice state) and anonymous public
write access (the Archive's "Submit a Summary," which publishes with no
approval queue). Each item from the phase-2 doc's Section 6, addressed
against what this app actually is -- honestly, not as a checklist to tick
without checking whether it applies.

## HTTPS everywhere

Already true by default: Vercel (frontend) and Render (backend) both
force HTTPS on every deployed URL, with no configuration needed on our
end. Nothing to change.

## Strong passwords / two-factor authentication

**Strong passwords**: there's no self-service password-set or -reset flow
today -- `scripts/create_justices.py` and `scripts/create_admin_user.py`
generate random passwords server-side (the justice-creation script uses
`secrets.token_urlsafe`, effectively unguessable), so there's currently no
UI path where a human picks a weak password to begin with. If a
self-service reset flow gets built later, it should validate length/
complexity then -- flagged as a real gap for that future work, not
addressed now since the flow doesn't exist yet.

**2FA**: genuinely out of scope for this pass. It's real work (TOTP
enrollment, backup codes, a recovery path when someone loses their
authenticator) for a roster of 7-9 people who already need a curator to
run a script to get an account in the first place -- the actual attack
surface it defends against here is narrow. Worth doing before the
Archive/recommendation-email features see heavier real use; not done now.
Tracked as a follow-up, not silently dropped.

## Rate-limiting public write endpoints

**Done**: `app/rate_limit.py`, a per-IP sliding-window counter, wired into
the two endpoints the doc names -- Archive submission
(`POST /api/archive`, 5 per 10 minutes per IP, Justices exempt since
they're not the abuse surface) and manual refresh (`POST /api/refresh`,
also 5 per 10 minutes per IP). The refresh endpoint already had a
*global* cooldown (`REFRESH_COOLDOWN_MINUTES`, Section 1) that's actually
stronger than a per-IP limit -- it blocks every visitor, not just one
address, once any refresh has run recently -- so the per-IP check there is
belt-and-suspenders, not the primary defense.

Honest limitation: this is in-process (a plain Python dict), correct for
this project's actual single-instance deployment (Render's free tier runs
one instance; Section 7 already frames the whole stack at "CUSG scale").
It resets on restart and wouldn't share state across multiple instances/
workers -- a real multi-instance deployment would need a shared store
(Redis, etc.) behind the same `check_rate_limit()` call signature.

## XSS sanitization on free-text fields

The real defense here is that this is a React frontend: JSX escapes text
content by default, and nothing in this codebase uses
`dangerouslySetInnerHTML` for `reflection_text`, `note` (the
recommendation reason), `submitted_by_name`, or any other user-supplied
field -- verified by checking every render path for these fields. A
`<script>` tag typed into a reflection renders as inert text, not markup.

That's the primary defense; two secondary, defense-in-depth measures
layer on top of it, both already in place: every free-text field has a
server-side length cap (Pydantic validators in `app/schemas.py`), and
`app/moderation.py`'s spam filter (built for abuse detection, not
security) incidentally catches the crudest injection attempts too (e.g. a
submission that's mostly URLs). Neither is the reason this app is safe
from XSS -- React's default escaping is -- but "sanitize the free-text
fields" from the doc is satisfied by the actual mechanism that does the
real work here, not a redundant server-side HTML-stripping pass that
would just duplicate what JSX already guarantees.

## CSRF protection on state-changing endpoints

**Doesn't apply to this app's actual auth model, and adding it would be
security theater.** CSRF works by exploiting *ambient* credentials --
cookies a browser attaches automatically to any request to a site,
including one triggered by a malicious third-party page the victim
happens to have open. This app's auth is a JWT **Bearer token** sent in
an explicit `Authorization` header, stored in `localStorage` and attached
by this app's own JavaScript on each request -- a cross-site page cannot
read another origin's `localStorage`, and cannot force a browser to
attach an `Authorization` header the way it can force a cookie along for
the ride. There is no ambient credential here for a forged cross-site
request to exploit.

This is a real architectural fact, not a gap papered over: token-based
APIs are a well-established alternative to CSRF tokens specifically
*because* they don't have this exposure. Building a CSRF-token mechanism
on top would add real complexity (issuing tokens, validating them,
threading them through every form) to defend against an attack this
authentication scheme is already not vulnerable to.

## Dependency hygiene

Checked via `pip list --outdated` (backend) and `npm outdated` (frontend)
for real, not assumed clean. This caught a genuine, live bug:

**`bcrypt` was outdated (4.0.1, latest 5.0.0) -- and upgrading it broke
password hashing entirely**, in a way worth documenting exactly because
it's a real trap for "just keep dependencies patched" advice. `app/
auth.py` hashed/verified passwords through `passlib`'s `CryptContext`,
and `passlib` 1.7.4 (its last release, in 2020) detects the installed
bcrypt version by reading `bcrypt.__about__.__version__` -- a submodule
`bcrypt` removed in 4.1+. With bcrypt 5.0 installed, that probe fails,
passlib's bcrypt backend silently falls back to a path that mishandles
the 72-byte input limit, and every `hash_password()`/`verify_password()`
call raised `ValueError`. The full test suite (91 tests) caught this
immediately after the upgrade -- exactly the scenario dependency updates
should always be run through a real test suite for, not applied and
assumed fine.

The actual fix wasn't "pin bcrypt back down" (that just defers the same
problem, and leaves a security-sensitive package outdated forever waiting
on an effectively unmaintained wrapper): `app/auth.py` now calls `bcrypt`
directly (`bcrypt.hashpw` / `bcrypt.checkpw`, two functions, no wrapper
needed for a single algorithm), and `passlib` was removed from
`requirements.txt` entirely. Backend now runs `bcrypt==5.0.0` and
`SQLAlchemy==2.0.53` (also outdated, patched clean), confirmed via the
full test suite passing (91/91) after both upgrades.

Frontend (`npm outdated`) showed only routine minor-version drift (React
19.2.x -> 19.3.0, Vite 8.2.2 -> 8.3.0, etc.) with no flagged
vulnerabilities -- left as-is rather than upgraded speculatively this late
in the build; a reasonable next thing for whoever maintains this to pick
up.

Ongoing practice going forward, now that the trap above is fixed rather
than hidden: keep dependencies patched, especially `fastapi`,
`sqlalchemy`, `python-jose` (JWT handling), and `bcrypt` (password
hashing) on the backend, and `react`/`react-router-dom` on the frontend --
but always through the real test suite, not applied blind.

## What this review deliberately didn't do

- Add a CSRF mechanism that doesn't apply (see above) -- would be
  net-negative: more code, no actual security gained, and it would
  misleadingly suggest cookie-based session risk this app doesn't have.
- Build 2FA speculatively before there's a real incentive/incident driving
  it, given the roster size and script-gated account creation already in
  place.
- Add HTML-sanitization libraries (DOMPurify, bleach, etc.) for a
  vulnerability class (stored XSS via free text) that React's default
  escaping already closes, and where no code path bypasses that escaping.
