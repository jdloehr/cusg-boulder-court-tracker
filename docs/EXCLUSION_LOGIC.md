# Juvenile & Sensitive-Case Exclusion Logic

Required by the build prompt, Section 12. Implements Section 4's legal/
ethical guardrails.

## Juvenile (`JV`, `JD`) -- automatic, unconditional

`app/jobs/docket_pull.py::upsert_row()` sets `is_excluded=True` (with
`exclusion_reason="Juvenile case (Section 4 default exclusion)"`) on every
row whose case number decodes to `CaseCategory.juvenile`, at insert time,
before the row is ever shown anywhere. This is a hard rule with no
admin override in the API: there is no endpoint that lets an Editor
un-exclude a juvenile case, because juvenile proceedings are typically
closed or restricted even when they technically appear in a scheduling
export (Section 4), and this tool should never nudge a student toward one.

`GET /api/hearings` also filters `is_excluded=False` unconditionally at the
query level, so an excluded row can't leak through by, say, a filter
combination the exclusion check didn't anticipate.

**Real-data note**: a live pull during build (see
[DATA_SOURCE_FINDINGS.md](DATA_SOURCE_FINDINGS.md)) found several hundred
real `JV`-prefixed rows in the Boulder County window; all were correctly
auto-excluded and none appeared in any `/api/hearings` response regardless
of filters used.

## Domestic Relations (`DR`) -- visible by default, curated judgment on top

Section 4 says `DR` hearings are public but often personally sensitive, and
that the curation team "should apply judgment rather than surfacing every
`DR` return-date/status hearing" as worth watching. This is implemented as
two independent layers, not a single flag:

1. **Type filtering already does most of the work.** The Section 5.1
   default view only shows `jury_trial` / `oral_argument_motions` hearings.
   A routine `DR` status conference or return date classifies as
   `hearing_type_category=other` (see
   [CASE_CATEGORY_DECODING.md](CASE_CATEGORY_DECODING.md)) and simply
   doesn't appear in the default list -- no special-casing needed. A
   contested custody *trial* or a `DR` motions hearing, which genuinely can
   be educational to watch, passes the same type filter as any other case
   category and *does* show up.
2. **`is_excluded` remains available as a manual Editor override**
   (`PATCH /api/admin/hearings/{id}/exclusion`, editor-role-gated) for the
   judgment call Section 4 asks for on a specific hearing -- e.g. an Editor
   decides a particular `DR` hearing is too personally sensitive to
   surface even though it technically matches the type filter. This is a
   per-hearing decision a human makes, not an automatic rule, which
   matches the build prompt's own instruction not to blanket-exclude the
   category.

No `DR` case is auto-excluded by the pipeline; the exclusion field is
reserved for the juvenile rule (automatic) and Editor judgment calls
(manual), which is also why `Hearing.is_excluded` is documented in
`app/models.py` as "juvenile/sensitive exclusion flag" -- one field, two
different triggers.

## What's never done

Per Section 4 ("never publish more personal detail about parties than the
docket itself already exposes"): `party_names` is stored and displayed
exactly as parsed from the docket export's `Name` column (see
`re_split_parties()` in `docket_pull.py`) -- no enrichment, no linking to
outside records, no attempt to identify parties beyond what the court's own
public docket already shows.

## Visitor-submitted content (added post-spec) -- same guardrails, moderated

The public "add details about this case" feature (`CommunitySubmission` --
see `app/models.py`) lets anyone browsing the site submit a summary or a
judge's name for a hearing. Because this is fully public and
unauthenticated (Section 7), Section 4's guardrails apply to what a random
visitor submits just as much as to what the automated pipelines pull in:

- A submission is never shown publicly, and never sets `Hearing.judge_name`,
  until an **Editor** approves it (`POST /api/admin/community-submissions/
  {id}/approve`) -- the same publish authority as blurbs and exclusion, not
  the lighter Contributor bar.
- `HearingOut`'s Pydantic schema filters `community_submissions` to
  `status=approved` as a belt-and-suspenders check (`app/schemas.py`), so a
  bug in one API call site can't accidentally leak a pending/rejected
  submission to the public API regardless of what the endpoint intended.
- A simple honeypot field (`website`) silently no-ops instead of erroring,
  so obvious bots don't even reach the review queue.
- The optional `submitter_context` field (e.g. "I was in the gallery") is
  never exposed by the public API or the public schema -- reviewer-only.

This is the same instinct as the juvenile/`DR` rules above, applied to a
new input surface the original spec didn't have: automation (or in this
case, an anonymous visitor) proposes, a human with Editor authority
disposes.
