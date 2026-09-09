# Case-Category & Hearing-Type Decoding

Required by the build prompt, Section 12: "Documentation of the case-category
decoding table and the juvenile/sensitive exclusion logic actually
implemented." Exclusion logic is in [EXCLUSION_LOGIC.md](EXCLUSION_LOGIC.md);
this document covers the two decoders that turn a raw docket-export row into
something a student can actually understand.

Both tables started as what Section 2.1 of the build prompt specified, and
were then **expanded against a real live pull** of ~5,000 Boulder County
hearings (see [DATA_SOURCE_FINDINGS.md](DATA_SOURCE_FINDINGS.md) section 4)
until 0% of that pull's rows were left in the "unrecognized" bucket. That's
a snapshot, not a guarantee -- new raw strings will still show up over time,
which is exactly what the admin review queue (Section 5.4) is for.

## 1. Case-category decoding (`backend/app/case_categories.py`)

Colorado trial-court case numbers are formatted `YYYY` + `TYPE-CODE` +
`SEQUENCE` (e.g. `2026CR001452`). The type code is decoded via
`CASE_PREFIX_TABLE`:

| Prefix | Category | Notes |
|---|---|---|
| `CR` | Criminal (felony) | |
| `M` | Misdemeanor | County criminal |
| `T`, `TR` | Traffic | |
| `CV` | Civil | District civil |
| `C` | Civil | County civil |
| `CC`, `SC` | Civil | Small claims (two-letter forms) |
| `S` | Civil | Small claims, single-letter form -- **not** in the original build prompt's table; added after live testing found real Boulder rows like `2025S165` paired with "Hearing on Citation" / "Court Trial" |
| `DR` | Domestic Relations | Divorce, custody |
| `JV`, `JD` | Juvenile | Excluded by default -- see EXCLUSION_LOGIC.md |
| `PR`, `R` | Probate | |

Anything that doesn't match (`decode_case_category()` returns
`recognized=False`) falls back to `CaseCategory.other` rather than raising
or guessing, and shows up in the admin review queue
(`GET /api/admin/review-queue/hearings`) for a human to look at. Extending
the table is a one-line addition to `CASE_PREFIX_TABLE` plus a test in
`tests/test_case_categories.py`.

The same module's `find_case_numbers_in_text()` reuses this prefix list
(loosened, no anchors) to extract candidate case numbers out of free-text
news articles for the Section 2.2 news-monitoring pipeline.

## 2. Hearing-type classification (`backend/app/hearing_types.py`)

The docket export's `Hearing Type` column is free text set per-courtroom,
not a fixed enum (Section 8 calls this "schema drift" explicitly). It's
classified into three buckets:

- **`jury_trial`** -- matches like "Jury Trial", "Trial to Jury".
- **`oral_argument_motions`** -- matches like "Oral Argument", "Motions
  Hearing", "Motion to Modify Hearing", "Suppression Hearing", and (added
  after live testing) "Preliminary Injunction" hearings, which are
  functionally the same thing: attorneys arguing a legal question in front
  of a judge, no jury.
- **`other`** -- recognized, but not one of the two focus types (e.g.
  "Sentencing", "Arraignment", "Return Date", "Pretrial Conference",
  "Show Cause Hearing" -- roughly 40 patterns as of this build, most of
  them added after the live pull showed they were common, not novel).
- **`unrecognized`** -- didn't match anything. Flagged for the admin review
  queue rather than silently bucketed as `other`, per Section 8.

Each match also carries a plain-language `hearing_type_display` string for
Section 5.2's detail view (e.g. the build prompt's own example: *"Oral
Argument / Motions Hearing: attorneys argue a legal question in front of
the judge, no witnesses or jury -- typically shorter and easier to follow
than a full trial."*).

**Adding a new pattern**: append a `(regex, category, display_or_None)`
tuple to `_RULES` in `hearing_types.py` -- order matters, first match wins,
so put specific patterns before generic ones (the bare `"Hearing"`
catch-all is deliberately last). Add a case to
`tests/test_hearing_types.py` alongside it.
