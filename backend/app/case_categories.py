"""
Case-number -> case-category decoding.

Colorado trial-court case numbers are formatted YYYY + TYPE-CODE + SEQUENCE,
e.g. "2026CR001234", "2026DR0456", "26M1234" (two-digit years appear on
some older/county records). This module decodes the TYPE-CODE into the
CaseCategory enum used throughout the app, per Section 2.1 of the build
prompt and Section 12's documentation requirement.

This is a *proxy* signal, not ground truth: the docket export gives us a
case number and hearing type but not the case caption or subject matter, so
the prefix is what we have to infer category (criminal vs. civil vs. family,
etc.) for filtering and for the juvenile-exclusion rule in Section 4.

IMPORTANT: this prefix table is not published anywhere as a fixed, versioned
spec by Colorado's judicial branch -- it is compiled from the well-known,
long-standing conventions documented in Colorado JDF/court-user materials
and cross-checked against real case numbers seen in Section 2.2's news
research (e.g. "20th Judicial District" filings). Treat it the same way the
build prompt treats `Hearing Type` strings (Section 8, "graceful schema
drift"): an unrecognized prefix should degrade to `other` and get flagged
for a human to look at, never crash the pipeline or get silently
mis-bucketed as something it isn't.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import CaseCategory

# Ordered longest-prefix-first so e.g. "DR" is checked before a hypothetical
# single-letter "D" entry. Keys are matched case-insensitively immediately
# after the leading year digits.
CASE_PREFIX_TABLE: dict[str, CaseCategory] = {
    "CR": CaseCategory.criminal,             # Criminal (felony)
    "M": CaseCategory.misdemeanor,           # Misdemeanor / county criminal
    "T": CaseCategory.traffic,               # Traffic
    "TR": CaseCategory.traffic,              # Traffic (alternate 2-letter form)
    "CV": CaseCategory.civil,                # Civil (district)
    "C": CaseCategory.civil,                 # Civil (county)
    "CC": CaseCategory.civil,                # County civil / small claims
    "SC": CaseCategory.civil,                # Small claims
    "S": CaseCategory.civil,                 # Small claims (single-letter form, e.g. "2025S165" --
                                              # confirmed against real Boulder County data during
                                              # build: paired with "Hearing on Citation"/"Court Trial")
    "DR": CaseCategory.domestic_relations,   # Domestic Relations (divorce, custody)
    "JV": CaseCategory.juvenile,             # Juvenile -- excluded by default, see Section 4
    "JD": CaseCategory.juvenile,             # Juvenile delinquency
    "PR": CaseCategory.probate,              # Probate
    "R": CaseCategory.probate,               # Probate (alternate form)
}

# Longest keys first so "CV" isn't accidentally matched by a "C"-prefix rule
# (regex alternation is first-match-wins).
_SORTED_PREFIXES = sorted(CASE_PREFIX_TABLE, key=len, reverse=True)

CASE_NUMBER_RE = re.compile(
    r"^(?P<year>\d{2}|\d{4})(?P<type>" + "|".join(_SORTED_PREFIXES) + r")(?P<seq>\d+)$",
    re.IGNORECASE,
)

# Used by the news-monitoring pipeline (Section 2.2) to find case numbers
# embedded in free-text articles, e.g. "case number 2026CR1234". Looser than
# CASE_NUMBER_RE (no anchors, no captured sequence-length limit) since we're
# scanning prose, not validating a known-good field.
CASE_NUMBER_IN_TEXT_RE = re.compile(
    r"\b(?P<year>20\d{2})\s?(?P<type>" + "|".join(_SORTED_PREFIXES) + r")\s?(?P<seq>\d{2,8})\b",
    re.IGNORECASE,
)


@dataclass
class CaseCategoryResult:
    category: CaseCategory
    recognized: bool  # False => prefix didn't match the table; flagged for review


def decode_case_category(case_number: str) -> CaseCategoryResult:
    """Decode a docket-export case number into a CaseCategory.

    Falls back to CaseCategory.other + recognized=False for anything that
    doesn't parse, rather than raising -- the docket-pull job uses
    `recognized` to route the row into the admin review queue (Section 5.4)
    instead of silently mis-categorizing or dropping it (Section 8).
    """
    if not case_number:
        return CaseCategoryResult(CaseCategory.other, recognized=False)

    cleaned = case_number.strip().upper().replace(" ", "").replace("-", "")
    match = CASE_NUMBER_RE.match(cleaned)
    if not match:
        return CaseCategoryResult(CaseCategory.other, recognized=False)

    type_code = match.group("type").upper()
    category = CASE_PREFIX_TABLE.get(type_code)
    if category is None:
        return CaseCategoryResult(CaseCategory.other, recognized=False)
    return CaseCategoryResult(category, recognized=True)


def find_case_numbers_in_text(text: str) -> list[str]:
    """Used by the news-monitoring job (Section 2.2) to pull candidate case
    numbers out of article text. Returns normalized case numbers
    (e.g. "2026CR1234"), deduplicated, in order of first appearance."""
    seen: list[str] = []
    for match in CASE_NUMBER_IN_TEXT_RE.finditer(text or ""):
        normalized = f"{match.group('year')}{match.group('type').upper()}{match.group('seq')}"
        if normalized not in seen:
            seen.append(normalized)
    return seen
