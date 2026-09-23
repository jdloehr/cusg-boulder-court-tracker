"""
Phase-6 doc: news-article-to-hearing matching, pulled out of
app/jobs/news_monitor.py (which stays responsible for fetching/parsing
feeds) so the same scoring logic can run both at ingestion time and as a
retroactive re-match pass (Section 5) over previously-unresolved rows.

Built against REAL evidence pulled from this project's own live
production data before writing a line of matching logic, not the Phase-6
doc's own assumption -- see the "Real diagnosis" note below. That
diagnosis is also why this module discards low/no-signal articles
outright instead of only ever queuing them (Section 3's own "or is
discarded if truly nothing matched" allowance): production's real
unmatched-review queue (487 rows, checked live) was almost entirely
non-court content -- school board votes, weather, opinion columns, a
governor's dog obituary -- because the RSS/WordPress feeds this pipeline
polls aren't pre-filtered to court content at all. A confidence-tiering
fix alone would not have touched that; it needed an explicit relevance
gate.

Real diagnosis (Phase-6 doc, Section 1 and Section 7 open question #2):
the Phase-6 doc assumed Colorado's docket export stores party names as
"LASTNAME, FIRSTNAME MIDDLE". Checked directly against 4,672 real,
currently-live production Hearing rows: every single one is
"FIRSTNAME [MIDDLE] LASTNAME", all caps (e.g. "JOHN CARLSTROM", "ABEL
CHAVARRIA MORQUECHO") -- already the same order news articles use, just
different case, which the existing `ilike` already handled. So a naive
exact/substring compare wasn't failing on word order. Cross-referencing
487 real unmatched articles against those 4,672 real names for a
same-person full-name co-occurrence found zero -- strong evidence that,
day to day, there simply isn't much natural overlap between what's in
the current docket window and what local news happens to cover on any
given day (consistent with this project's own original build finding:
"no naturally-occurring auto-match happened to occur during build ...
an honest data fact, not a bug" -- docs/DATA_SOURCE_FINDINGS.md). The
matching logic below is still meaningfully stronger than before (fuzzy
first-name/middle-initial tolerance, date-proximity gating, category-
consistency downweighting) because those are real, worthwhile
improvements on their own merits -- just not, on the evidence, the
primary reason the queue looked broken. The queue's actual noise problem
was.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy.orm import Session

from app.models import CaseCategory, Hearing, HearingStatus, MatchConfidence

# A couple of weeks either side, per the doc's own suggestion -- wide
# enough to cover a docket date that's since moved (continuances are
# common) without being so wide it starts matching an unrelated older
# case for a common name.
DATE_WINDOW_DAYS = 21

# A name match needs at least this score to count as "strong" for
# Section 3's high-confidence tier (case number found, or a strong name
# match plus date-proximity agreement). 1.0 = exact full-name match;
# 0.9 = last name exact + first initial matches a full first name.
STRONG_NAME_SCORE = 0.85

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def normalize_name_tokens(name: str) -> list[str]:
    """Lowercase, strip punctuation, drop generational suffixes. Order-
    preserving -- the caller decides which token is "last name" (this
    project's real data is consistently "first [middle] last", confirmed
    live -- see this module's docstring)."""
    cleaned = re.sub(r"[^\w\s]", "", name or "").lower()
    return [t for t in cleaned.split() if t and t not in _SUFFIXES]


def name_match_score(candidate: str, party_name: str) -> float:
    """0.0-1.0. The last-name token is the anchor: two names that don't
    share one are never considered a match at all (0.0), regardless of
    how similar the rest looks -- this is deliberately strict, since a
    shared first name alone (candidate="John Smith" vs party="John
    Carlstrom") is essentially meaningless as a person-identifying
    signal. Once the last name matches, the first-name comparison is
    tolerant of a middle initial, a missing middle name, or a nickname/
    minor spelling difference, since none of those should sink an
    otherwise-strong match."""
    cand = normalize_name_tokens(candidate)
    party = normalize_name_tokens(party_name)
    if len(cand) < 2 or len(party) < 2:
        return 0.0
    if cand[-1] != party[-1]:
        return 0.0

    cand_first, party_first = cand[0], party[0]
    if cand_first == party_first:
        first_score = 1.0
    elif len(cand_first) == 1 or len(party_first) == 1:
        # One side is just an initial ("J." vs "John") -- credit a match
        # on that initial, short of a full first-name match.
        first_score = 0.8 if cand_first[0] == party_first[0] else 0.0
    else:
        first_score = SequenceMatcher(None, cand_first, party_first).ratio()

    # A confirmed last-name match is already meaningful on its own (0.5
    # floor); the first-name comparison scales the remaining 0.5.
    return 0.5 + 0.5 * first_score


def date_proximity_days(article_date: Optional[datetime], hearing_date: date) -> Optional[int]:
    if article_date is None or hearing_date is None:
        return None
    return abs((hearing_date - article_date.date()).days)


# Lightweight, deliberately simple keyword sets -- this is a downweighting
# signal (Section 2's "lower confidence, not auto-match"), not a
# classifier that needs to be exhaustive or precise on its own.
_CRIMINAL_KEYWORDS = {
    "arrest", "arrested", "charge", "charged", "charges", "sentence", "sentenced",
    "sentencing", "convicted", "conviction", "guilty", "plea", "pleaded", "indicted",
    "indictment", "warrant", "felony", "misdemeanor", "prosecutor", "prosecution",
    "district attorney", "acquitted", "bond", "bail", "arraignment",
}
_DOMESTIC_RELATIONS_KEYWORDS = {
    "divorce", "custody dispute", "child custody", "restraining order",
    "protective order", "domestic relations", "child support",
}
# Broader than the criminal set above -- used only to decide whether an
# article with no case number and no confident name match is worth a
# human's attention at all, not to guess at a specific case category.
_COURT_RELEVANCE_KEYWORDS = _CRIMINAL_KEYWORDS | _DOMESTIC_RELATIONS_KEYWORDS | {
    "court", "judge", "trial", "jury", "hearing", "lawsuit", "sued", "lawsuit",
    "verdict", "sheriff", "detained", "arraign", "probation", "custody",
    "plaintiff", "defendant", "grand jury", "subpoena",
}


def has_court_relevance(text: str) -> bool:
    lowered = (text or "").lower()
    return any(kw in lowered for kw in _COURT_RELEVANCE_KEYWORDS)


def _guess_article_category(text: str) -> Optional[CaseCategory]:
    """Best-effort, used only to demote an otherwise-strong match, never
    to promote one -- see category_consistent's docstring below."""
    lowered = (text or "").lower()
    if any(kw in lowered for kw in _DOMESTIC_RELATIONS_KEYWORDS):
        return CaseCategory.domestic_relations
    if any(kw in lowered for kw in _CRIMINAL_KEYWORDS):
        return CaseCategory.criminal
    return None


def category_consistent(text: str, hearing_category: CaseCategory) -> Optional[bool]:
    """None when the article's language doesn't clearly suggest a
    category at all (the common case -- most articles don't read as
    unambiguously "criminal" or "domestic" in isolation); True/False only
    when it does. A clear signal that *disagrees* with the candidate
    hearing's actual category is what Section 2 asks for: "a signal to
    lower confidence rather than auto-match," not proof the match is
    wrong outright (e.g. a criminal case can still get covered using
    lawsuit-adjacent language)."""
    guess = _guess_article_category(text)
    if guess is None:
        return None
    return guess == hearing_category


@dataclass
class MatchEvaluation:
    """Everything Section 1's diagnosis logging and Section 6's
    match_signals column need, in one place -- built once per article,
    logged once, then either persisted onto the NewsMention row or used
    to decide there's nothing worth persisting a mention for at all
    (see should_discard)."""
    hearing: Optional[Hearing] = None
    confidence: Optional[MatchConfidence] = None
    signals: dict = field(default_factory=dict)

    @property
    def should_discard(self) -> bool:
        """True when there's genuinely nothing here for a human to act
        on: no case number, no hearing candidate at all, and no language
        suggesting this is even court-related. See this module's
        docstring for the real evidence behind this gate."""
        return (
            self.hearing is None
            and not self.signals.get("case_numbers_found")
            and not self.signals.get("court_relevance")
        )


def _lookup_by_case_number(db: Session, case_numbers: list[str]) -> Optional[Hearing]:
    for case_number in case_numbers:
        hearing = (
            db.query(Hearing)
            .filter(Hearing.case_number.ilike(case_number), Hearing.status != HearingStatus.cancelled)
            .first()
        )
        if hearing:
            return hearing
    return None


def _candidate_hearings(db: Session, published_at: Optional[datetime]) -> list[Hearing]:
    """SQL-level date pre-filter before any Python-side name scoring --
    at this project's real scale (thousands of hearings across a rolling
    docket window) scoring every article against every hearing's every
    party name would be needlessly expensive; a date window this narrow
    also directly implements Section 2's date-proximity requirement,
    not just an optimization on top of it."""
    q = db.query(Hearing).filter(Hearing.status != HearingStatus.cancelled, Hearing.party_names.isnot(None))
    if published_at is not None:
        window_start = published_at.date() - timedelta(days=DATE_WINDOW_DAYS)
        window_end = published_at.date() + timedelta(days=DATE_WINDOW_DAYS)
        q = q.filter(Hearing.date >= window_start, Hearing.date <= window_end)
    return q.all()


def evaluate_match(
    db: Session, case_numbers: list[str], party_candidates: list[str],
    published_at: Optional[datetime], full_text: str,
) -> MatchEvaluation:
    """The single entry point both ingestion (news_monitor.py) and the
    retroactive re-match pass (Section 5, below) call. Never raises --
    worst case, returns an evaluation with no hearing and low/no
    signals."""
    signals: dict = {
        "case_numbers_found": case_numbers,
        "case_number_matched": None,
        "party_candidates_found": party_candidates,
        "name_match_score": None,
        "name_match_candidate": None,
        "name_match_party_name": None,
        "date_proximity_days": None,
        "category_consistent": None,
        "court_relevance": has_court_relevance(full_text),
    }

    # 1. Case number: the strongest possible signal, no date/category
    # gating -- an exact case-number match is unambiguous regardless of
    # when the article ran.
    hearing = _lookup_by_case_number(db, case_numbers)
    if hearing:
        signals["case_number_matched"] = hearing.case_number
        return MatchEvaluation(hearing=hearing, confidence=MatchConfidence.high, signals=signals)

    # 2. Name-based candidates, scored against hearings in the date
    # window only.
    if party_candidates:
        best_score = 0.0
        best_hearing: Optional[Hearing] = None
        best_party_name: Optional[str] = None
        best_candidate: Optional[str] = None
        best_days: Optional[int] = None

        for h in _candidate_hearings(db, published_at):
            try:
                names = json.loads(h.party_names) if h.party_names else []
            except (json.JSONDecodeError, TypeError):
                continue
            for party_name in names:
                for candidate in party_candidates:
                    score = name_match_score(candidate, party_name)
                    if score > best_score:
                        best_score = score
                        best_hearing = h
                        best_party_name = party_name
                        best_candidate = candidate
                        best_days = date_proximity_days(published_at, h.date)

        if best_hearing is not None:
            signals["name_match_score"] = round(best_score, 3)
            signals["name_match_candidate"] = best_candidate
            signals["name_match_party_name"] = best_party_name
            signals["date_proximity_days"] = best_days
            consistent = category_consistent(full_text, best_hearing.case_category)
            signals["category_consistent"] = consistent

            date_agrees = best_days is not None and best_days <= DATE_WINDOW_DAYS
            if best_score >= STRONG_NAME_SCORE and date_agrees and consistent is not False:
                return MatchEvaluation(hearing=best_hearing, confidence=MatchConfidence.high, signals=signals)
            # Weaker signal agreement (fuzzy first name, no known
            # publish date, or a category mismatch downgrading an
            # otherwise-strong match) -- still a real candidate, just
            # not confident enough to auto-attach.
            return MatchEvaluation(hearing=best_hearing, confidence=MatchConfidence.medium, signals=signals)

    # 3. Nothing matched. should_discard (on the returned evaluation)
    # decides whether this is worth queuing at all.
    return MatchEvaluation(hearing=None, confidence=MatchConfidence.low, signals=signals)
