"""
Phase 9 doc: matching logic for LearnTopic -- "every hearing of a given
type/category automatically links to its matching topic entry." Not a
stored relationship (see LearnTopic's docstring in app/models.py); this
is a lookup run at read time.
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Hearing, LearnTopic
from app.schemas import ExternalLinkOut, LearnTopicOut, parse_external_links


def matching_learn_topics(db: Session, hearing: Hearing) -> list[LearnTopic]:
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
    least an honest reflection of what got saved."""
    return (
        db.query(LearnTopic)
        .filter(
            or_(
                LearnTopic.applies_to_hearing_type_category.is_(None),
                LearnTopic.applies_to_hearing_type_category == hearing.hearing_type_category,
            ),
            or_(
                LearnTopic.applies_to_case_category.is_(None),
                LearnTopic.applies_to_case_category == hearing.case_category,
            ),
        )
        .order_by(LearnTopic.title)
        .all()
    )


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
