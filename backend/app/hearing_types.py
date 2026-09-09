"""
Hearing-type classification and plain-language explanation.

The docket export's `Hearing Type` column (Section 2.1) is free text set by
each courtroom's clerk, not a fixed enum Colorado publishes and guarantees
stable -- Section 8 calls this out explicitly ("graceful schema drift
handling"). This module:

1. Buckets a raw hearing-type string into HearingTypeCategory
   (jury_trial / oral_argument_motions / other), which drives the default
   filtering in Section 5.1.
2. Produces a plain-language `hearing_type_display` string for Section 5.2's
   hearing detail view.
3. Flags anything it doesn't recognize as HearingTypeCategory.unrecognized
   instead of guessing -- those rows go to the admin review queue
   (Section 5.4) for a human to categorize, and that categorization should
   get added back into CLASSIFICATION_RULES below over time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import HearingTypeCategory

PLAIN_LANGUAGE = {
    HearingTypeCategory.jury_trial: (
        "Jury Trial: a full trial where a jury of citizens decides the "
        "outcome after hearing evidence and witness testimony. Usually the "
        "most substantial proceeding to observe, and can run multiple days."
    ),
    HearingTypeCategory.oral_argument_motions: (
        "Oral Argument / Motions Hearing: attorneys argue a legal question "
        "in front of the judge, no witnesses or jury -- typically shorter "
        "and easier to follow than a full trial."
    ),
}

# (raw-text regex, category, specific display override or None to use the
# category-level PLAIN_LANGUAGE text above). Order matters: first match
# wins, so more specific patterns are listed before broader ones.
_RULES: list[tuple[re.Pattern, HearingTypeCategory, str | None]] = [
    (re.compile(r"\bjury\s*trial\b", re.I), HearingTypeCategory.jury_trial, None),
    (re.compile(r"\btrial\s*to\s*jury\b", re.I), HearingTypeCategory.jury_trial, None),
    (re.compile(r"\boral\s*argument", re.I), HearingTypeCategory.oral_argument_motions, None),
    (re.compile(r"\bmotion[s]?\s*hearing", re.I), HearingTypeCategory.oral_argument_motions, None),
    (re.compile(r"\bhearing\s*on\s*motion", re.I), HearingTypeCategory.oral_argument_motions, None),
    (re.compile(r"\bmotion\s*to\s*modify", re.I), HearingTypeCategory.oral_argument_motions, None),
    (re.compile(r"\bsuppress(ion)?\s*hearing", re.I), HearingTypeCategory.oral_argument_motions,
     "Motions Hearing (Suppression): attorneys argue whether certain "
     "evidence can be used at trial. No jury -- decided by the judge."),

    # Known-common types that are neither of our two focus categories, but
    # ARE recognized (not schema drift) -- bucketed as "other" so they don't
    # clutter the default view but display cleanly if a curator surfaces one
    # via a news mention (Section 2.2) or manual add.
    (re.compile(r"\bcourt\s*trial\b|\bbench\s*trial\b", re.I), HearingTypeCategory.other,
     "Bench Trial: a full trial decided by the judge alone, no jury."),
    (re.compile(r"\bsentenc", re.I), HearingTypeCategory.other,
     "Sentencing: the judge formally imposes the sentence after a "
     "conviction or guilty plea."),
    (re.compile(r"\barraign", re.I), HearingTypeCategory.other,
     "Arraignment: a defendant's first formal court appearance to hear the "
     "charges and enter a plea. Brief and procedural."),
    (re.compile(r"\badvisement", re.I), HearingTypeCategory.other,
     "Hearing on Advisement: the judge advises a defendant of their rights "
     "and the charges against them. Brief and procedural."),
    (re.compile(r"\breturn\s*date\b", re.I), HearingTypeCategory.other,
     "Return Date: a brief scheduling check-in, not a substantive hearing."),
    (re.compile(r"\bpermanent\s*orders\b", re.I), HearingTypeCategory.other,
     "Permanent Orders Hearing: final decisions in a domestic relations "
     "case (e.g. property division, parenting time)."),
    (re.compile(r"\bstatus\s*conference\b", re.I), HearingTypeCategory.other,
     "Status Conference: a brief scheduling/procedural check-in with the "
     "judge, not a substantive hearing."),
    (re.compile(r"\bdisposition\b", re.I), HearingTypeCategory.other,
     "Disposition Hearing: the case is resolved, often via plea agreement."),
    (re.compile(r"\bpreliminary\s*hearing\b", re.I), HearingTypeCategory.other,
     "Preliminary Hearing: the judge decides if there's enough evidence for "
     "a felony case to proceed."),

    # The rules below were added after running the pipeline against a real
    # live pull (see docs/DATA_SOURCE_FINDINGS.md): roughly 43% of real rows
    # were falling into `unrecognized` on the first pass, and this is what
    # those raw strings actually were -- real, well-established Colorado
    # hearing types, not schema drift. Recognizing them (as `other`, since
    # none are jury trials or oral argument/motions) keeps the admin review
    # queue focused on genuinely novel strings instead of routine ones.
    (re.compile(r"\bpreliminary\s*injunction\b", re.I), HearingTypeCategory.oral_argument_motions,
     "Preliminary Injunction Hearing: attorneys argue whether the court "
     "should block an action while the case proceeds -- legal argument in "
     "front of the judge, similar to a motions hearing."),
    (re.compile(r"\breview\s*hearing\b|\breview\s*w.?appearance\b", re.I), HearingTypeCategory.other,
     "Review Hearing: a brief check-in on case status or compliance, not a "
     "substantive hearing."),
    (re.compile(r"\bfirst\s*hearing\b|\binitial\s*conference\b", re.I), HearingTypeCategory.other,
     "Initial Hearing/Conference: a case's first scheduled court appearance."),
    (re.compile(r"\brtrn\b.*\bsumm.*\bprob\b", re.I), HearingTypeCategory.other,
     "Return on Summons for Review of Probate: a scheduling/compliance "
     "check-in in a probate case."),
    (re.compile(r"\brtrn\s*filing\s*of\s*charges\b", re.I), HearingTypeCategory.other,
     "Return on Filing of Charges: a brief scheduling hearing after "
     "charges are filed."),
    (re.compile(r"\bpermanent\s*restraining\b", re.I), HearingTypeCategory.other,
     "Permanent Restraining Order Hearing: the court decides whether to "
     "make a restraining order permanent."),
    (re.compile(r"\bpermanent\s*planning\b", re.I), HearingTypeCategory.other,
     "Permanent Planning Hearing: a dependency/juvenile-court hearing on a "
     "child's long-term placement plan."),
    (re.compile(r"\bnon.?contested\b", re.I), HearingTypeCategory.other,
     "Non-Contested Hearing: both sides agree, so the hearing is brief and procedural."),
    (re.compile(r"\bpre.?trial\s*(conference|readiness)\b", re.I), HearingTypeCategory.other,
     "Pretrial Conference: attorneys and the judge coordinate logistics "
     "ahead of trial -- not open argument on a legal issue."),
    (re.compile(r"\bappearance\s*on\s*bond\b", re.I), HearingTypeCategory.other,
     "Appearance on Bond: a brief hearing confirming bond conditions."),
    (re.compile(r"\bpetition\s*to\s*seal\b", re.I), HearingTypeCategory.other,
     "Hearing on Petition to Seal: the court considers sealing a case's "
     "records from public view."),
    (re.compile(r"\bhearing\s*on\s*citation\b", re.I), HearingTypeCategory.other,
     "Hearing on Citation: a brief hearing on a traffic or municipal citation."),
    (re.compile(r"\bappearance\s*on\s*arrest\s*warrant\b", re.I), HearingTypeCategory.other,
     "Appearance on Arrest Warrant: a defendant's first appearance after "
     "being arrested on a warrant."),
    (re.compile(r"\btemporary\s*orders\b", re.I), HearingTypeCategory.other,
     "Temporary Orders Hearing: the court sets interim domestic-relations "
     "orders (e.g. parenting time) while the case is pending."),
    (re.compile(r"\badjudicatory\b", re.I), HearingTypeCategory.other,
     "Adjudicatory Hearing: the court determines whether the allegations "
     "in the case are proven (common in juvenile/dependency matters)."),
    (re.compile(r"\bshow\s*cause\b", re.I), HearingTypeCategory.other,
     "Show Cause Hearing: a party must explain to the court why it "
     "shouldn't take a particular action (e.g. contempt, revocation)."),
    (re.compile(r"\bcase\s*management\s*conference\b", re.I), HearingTypeCategory.other,
     "Case Management Conference: a procedural scheduling check-in."),
    (re.compile(r"\bconservatorship\b|\bcons.?guardianship\b|\bguardianship\b", re.I), HearingTypeCategory.other,
     "Conservatorship/Guardianship Hearing: a probate-court hearing on "
     "managing someone's affairs or care."),
    (re.compile(r"\bterm(ination)?\s*of\s*parental\s*rights\b", re.I), HearingTypeCategory.other,
     "Termination of Parental Rights Hearing: a substantial dependency-court "
     "hearing deciding whether to permanently end a parent's legal rights."),
    (re.compile(r"\bpaternity\b", re.I), HearingTypeCategory.other,
     "Paternity Hearing: the court establishes or contests legal parentage."),
    (re.compile(r"\bsocial\s*svcs?\s*support\b", re.I), HearingTypeCategory.other,
     "Social Services Support Hearing: a status hearing in a case involving "
     "county human/social services."),
    (re.compile(r"\bfinal\s*hearing\b", re.I), HearingTypeCategory.other,
     "Final Hearing: the concluding hearing in the case."),
    (re.compile(r"\bhrg\s*revocation|\brevocation\s*of\s*(probation|deferred)\b", re.I),
     HearingTypeCategory.other,
     "Hearing on Revocation: the court considers whether a probation or "
     "deferred-sentence violation occurred."),
    (re.compile(r"\brule\s*120\b", re.I), HearingTypeCategory.other,
     "Rule 120 Hearing: a foreclosure-related hearing authorizing a "
     "trustee's sale."),
    (re.compile(r"\bname\s*change\b", re.I), HearingTypeCategory.other,
     "Name Change Hearing."),
    (re.compile(r"\bextreme\s*risk\b", re.I), HearingTypeCategory.other,
     "Extreme Risk Protection Order Hearing (Colorado's \"red flag\" law)."),
    (re.compile(r"\bgarnishment\b", re.I), HearingTypeCategory.other,
     "Garnishment Objection Hearing."),
    (re.compile(r"\bfed\s*hearing\b", re.I), HearingTypeCategory.other,
     "Forcible Entry and Detainer (Eviction) Hearing."),
    (re.compile(r"\bcompetency\b", re.I), HearingTypeCategory.other,
     "Competency Hearing: the court considers whether a defendant is "
     "mentally competent to proceed -- often involves expert testimony "
     "rather than legal argument alone."),
    # Deliberately last and deliberately vague: a bare "Hearing" with no
    # other descriptive text. This is recognized (not schema drift -- we've
    # seen it repeatedly in real data) but genuinely uninformative, so it's
    # bucketed as `other` without pretending to know more than the docket
    # export tells us.
    (re.compile(r"^\s*hearing\s*$", re.I), HearingTypeCategory.other,
     "Hearing: purpose not specified in the docket export."),
]


@dataclass
class HearingTypeResult:
    category: HearingTypeCategory
    display: str
    recognized: bool


def classify_hearing_type(raw: str) -> HearingTypeResult:
    raw = (raw or "").strip()
    if not raw:
        return HearingTypeResult(HearingTypeCategory.unrecognized, "(no hearing type given)", recognized=False)

    for pattern, category, override_display in _RULES:
        if pattern.search(raw):
            display = override_display or PLAIN_LANGUAGE.get(category, raw)
            return HearingTypeResult(category, display, recognized=True)

    # Schema drift: an hearing-type string we've never seen. Don't guess --
    # surface the raw string as-is and flag it for the admin review queue.
    return HearingTypeResult(
        HearingTypeCategory.unrecognized,
        f"{raw} (unrecognized hearing type -- pending review)",
        recognized=False,
    )
