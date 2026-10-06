"""
Phase 9 doc: matching logic for LearnTopic -- "every hearing of a given
type/category automatically links to its matching topic entry." Not a
stored relationship (see LearnTopic's docstring in app/models.py); this
is a lookup run at read time.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Hearing, LearnTopic
from app.schemas import ExternalLinkOut, LearnTopicOut, parse_external_links


def load_all_learn_topics(db: Session) -> list[LearnTopic]:
    """Every LearnTopic row, loaded once. A handful of rows at this
    project's real scale -- always cheaper to load in full than to
    re-query per hearing, see topics_matching_hearing below."""
    return db.query(LearnTopic).order_by(LearnTopic.title).all()


def topics_matching_hearing(topics: list[LearnTopic], hearing: Hearing) -> list[LearnTopic]:
    """A topic matches a hearing if every dimension the topic actually
    specifies agrees with that hearing -- an unset dimension on the topic
    means "matches any value," not "matches nothing." A hearing can
    therefore match more than one topic (e.g. a general "Jury Trial"
    explainer and a separate general "Criminal Cases" explainer both
    apply to one specific criminal jury trial) -- see the doc's own "zero
    or more" framing. A topic with *both* dimensions unset would match
    every hearing site-wide; routers/learn.py rejects creating one like
    that, but this function doesn't re-check it, so an existing one
    (however it got there) still simply matches everything, which is at
    least an honest reflection of what got saved.

    Takes an already-loaded `topics` list and filters it in Python,
    rather than querying the database itself -- see
    matching_learn_topics's docstring for why that distinction matters."""
    return [
        t for t in topics
        if (t.applies_to_hearing_type_category is None
            or t.applies_to_hearing_type_category == hearing.hearing_type_category)
        and (t.applies_to_case_category is None or t.applies_to_case_category == hearing.case_category)
    ]


def matching_learn_topics(db: Session, hearing: Hearing) -> list[LearnTopic]:
    """Single-hearing convenience wrapper (one query, for call sites --
    the hearing-detail endpoint, this module's own tests -- that only
    ever need one hearing's matches at a time).

    Oct 2026 review item 10: GET /api/hearings used to call this once
    per row in its result set -- a real N+1 query pattern that scales
    with how many hearings are in the requested window, not with how
    many Learn topics exist (which is always small). That endpoint now
    calls load_all_learn_topics() once and topics_matching_hearing()
    per row instead, in memory; this wrapper is unchanged for everyone
    else."""
    return topics_matching_hearing(load_all_learn_topics(db), hearing)


def learn_topic_out(t: LearnTopic) -> LearnTopicOut:
    """Shared builder -- both routers/learn.py's own endpoints and
    routers/public.py's Hearing embedding need the exact same shape."""
    return LearnTopicOut(
        id=t.id, title=t.title,
        applies_to_hearing_type_category=t.applies_to_hearing_type_category,
        applies_to_case_category=t.applies_to_case_category,
        body_text=t.body_text, video_url=t.video_url,
        has_uploaded_video=bool(t.video_data),
        external_links=[ExternalLinkOut(**link) for link in parse_external_links(t.external_links)],
        created_by_display_name=(t.created_by.display_name or t.created_by.email) if t.created_by else None,
        created_at=t.created_at, updated_at=t.updated_at,
    )
