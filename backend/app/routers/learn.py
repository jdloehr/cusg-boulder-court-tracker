"""
Phase 9 doc: the "Learn" teaching feature.

Two kinds of content, both restricted to Justices for creation -- "the
existing Editor/admin role" is the doc's own explicit phrase for the
role check to reuse, so every mutating endpoint here uses require_editor,
the same dependency routers/admin.py already uses for the admin/curation
tool's own content-publishing actions (blurb publish, exclusion). Every
real Justice account already has role=editor by construction (Phase-3
doc, Section 2's merge decision -- see AdminUser's docstring), so this
is "Justices only" in practice without inventing a third role check
alongside require_editor/require_justice:

- LearnTopic: a reusable explainer matched by hearing type/case category
  (see app/learn.py) -- public browsable library + auto-surfaced on
  every matching hearing's detail page.
- CaseTeachingNote: an optional, one-off note tied to one specific
  Hearing -- a real FK, not a type/category match (see CaseTeachingNote's
  docstring in app/models.py).

Video: a Justice can either paste a URL (YouTube/Vimeo/direct file,
embedded appropriately by the frontend) or upload a file directly, stored
the same way AdminUser's profile photo is (Postgres BYTEA, served via a
dedicated GET endpoint) -- see app/video_upload.py's docstring for why
video's validation and size cap differ from photo.py's.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import require_editor
from app.db import get_db
from app.learn import learn_topic_out
from app.models import (
    AdminUser,
    CaseCategory,
    CaseTeachingNote,
    Hearing,
    HearingTypeCategory,
    LearnTopic,
)
from app.routers.archive import create_archive_entry
from app.schemas import (
    ArchiveEntryIn,
    CaseTeachingNoteIn,
    CaseTeachingNoteOut,
    CaseTeachingNoteUpdateIn,
    CopyToArchiveIn,
    ExternalLinkOut,
    LearnTopicIn,
    LearnTopicOut,
    LearnTopicUpdateIn,
    parse_external_links,
)
from app.video_upload import InvalidVideoError, process_video_upload

router = APIRouter(tags=["learn"])


def _links_out(raw: Optional[str]) -> list[ExternalLinkOut]:
    return [ExternalLinkOut(**link) for link in parse_external_links(raw)]


def _teaching_note_out(n: CaseTeachingNote) -> CaseTeachingNoteOut:
    return CaseTeachingNoteOut(
        id=n.id, hearing_id=n.hearing_id, body_text=n.body_text, video_url=n.video_url,
        has_uploaded_video=bool(n.video_data),
        external_links=_links_out(n.external_links),
        created_by_display_name=(n.created_by.display_name or n.created_by.email) if n.created_by else None,
        created_at=n.created_at, updated_at=n.updated_at,
    )


# --- LearnTopic: public browsable library --------------------------------

@router.get("/api/learn-topics", response_model=list[LearnTopicOut])
def list_learn_topics(
    db: Session = Depends(get_db),
    hearing_type_category: Optional[HearingTypeCategory] = None,
    case_category: Optional[CaseCategory] = None,
):
    q = db.query(LearnTopic)
    if hearing_type_category:
        q = q.filter(LearnTopic.applies_to_hearing_type_category == hearing_type_category)
    if case_category:
        q = q.filter(LearnTopic.applies_to_case_category == case_category)
    topics = q.order_by(LearnTopic.title).all()
    return [learn_topic_out(t) for t in topics]


@router.get("/api/learn-topics/{topic_id}", response_model=LearnTopicOut)
def get_learn_topic(topic_id: str, db: Session = Depends(get_db)):
    topic = db.query(LearnTopic).filter(LearnTopic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Learn topic not found")
    return learn_topic_out(topic)


@router.get("/api/learn-topics/{topic_id}/video")
def get_learn_topic_video(topic_id: str, db: Session = Depends(get_db)):
    topic = db.query(LearnTopic).filter(LearnTopic.id == topic_id).first()
    if not topic or not topic.video_data:
        raise HTTPException(404, "No uploaded video")
    return Response(content=topic.video_data, media_type=topic.video_content_type or "video/mp4")


@router.post("/api/admin/learn-topics", response_model=LearnTopicOut, status_code=201)
def create_learn_topic(payload: LearnTopicIn, db: Session = Depends(get_db),
                        admin: AdminUser = Depends(require_editor)):
    topic = LearnTopic(
        title=payload.title,
        applies_to_hearing_type_category=payload.applies_to_hearing_type_category,
        applies_to_case_category=payload.applies_to_case_category,
        body_text=payload.body_text,
        video_url=payload.video_url,
        external_links=json.dumps([link.model_dump() for link in payload.external_links]),
        created_by_id=admin.id,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return learn_topic_out(topic)


@router.patch("/api/admin/learn-topics/{topic_id}", response_model=LearnTopicOut)
def update_learn_topic(topic_id: str, payload: LearnTopicUpdateIn, db: Session = Depends(get_db),
                        admin: AdminUser = Depends(require_editor)):
    topic = db.query(LearnTopic).filter(LearnTopic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Learn topic not found")

    data = payload.model_dump(exclude_unset=True)
    if "external_links" in data and data["external_links"] is not None:
        data["external_links"] = json.dumps(data["external_links"])
    for field, value in data.items():
        setattr(topic, field, value)

    new_type = data.get("applies_to_hearing_type_category", topic.applies_to_hearing_type_category)
    new_case = data.get("applies_to_case_category", topic.applies_to_case_category)
    if not new_type and not new_case:
        raise HTTPException(400, "Set at least one of hearing type or case category, or this topic would never match anything")

    topic.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(topic)
    return learn_topic_out(topic)


@router.delete("/api/admin/learn-topics/{topic_id}", status_code=204)
def delete_learn_topic(topic_id: str, db: Session = Depends(get_db), admin: AdminUser = Depends(require_editor)):
    topic = db.query(LearnTopic).filter(LearnTopic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Learn topic not found")
    db.delete(topic)
    db.commit()


@router.put("/api/admin/learn-topics/{topic_id}/video", response_model=LearnTopicOut)
async def upload_learn_topic_video(topic_id: str, db: Session = Depends(get_db),
                                    file: UploadFile = File(...),
                                    admin: AdminUser = Depends(require_editor)):
    topic = db.query(LearnTopic).filter(LearnTopic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Learn topic not found")
    raw = await file.read()
    try:
        video_bytes, content_type = process_video_upload(raw, file.content_type or "")
    except InvalidVideoError as exc:
        raise HTTPException(400, str(exc)) from exc
    topic.video_data = video_bytes
    topic.video_content_type = content_type
    topic.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(topic)
    return learn_topic_out(topic)


# --- CaseTeachingNote: attached to one specific Hearing -------------------

@router.post("/api/admin/hearings/{hearing_id}/teaching-notes", response_model=CaseTeachingNoteOut, status_code=201)
def create_teaching_note(hearing_id: str, payload: CaseTeachingNoteIn, db: Session = Depends(get_db),
                          admin: AdminUser = Depends(require_editor)):
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    note = CaseTeachingNote(
        hearing_id=hearing.id, body_text=payload.body_text, video_url=payload.video_url,
        external_links=json.dumps([link.model_dump() for link in payload.external_links]),
        created_by_id=admin.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _teaching_note_out(note)


@router.patch("/api/admin/teaching-notes/{note_id}", response_model=CaseTeachingNoteOut)
def update_teaching_note(note_id: str, payload: CaseTeachingNoteUpdateIn, db: Session = Depends(get_db),
                          admin: AdminUser = Depends(require_editor)):
    note = db.query(CaseTeachingNote).filter(CaseTeachingNote.id == note_id).first()
    if not note:
        raise HTTPException(404, "Teaching note not found")
    data = payload.model_dump(exclude_unset=True)
    if "external_links" in data and data["external_links"] is not None:
        data["external_links"] = json.dumps(data["external_links"])
    for field, value in data.items():
        setattr(note, field, value)
    note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(note)
    return _teaching_note_out(note)


@router.delete("/api/admin/teaching-notes/{note_id}", status_code=204)
def delete_teaching_note(note_id: str, db: Session = Depends(get_db), admin: AdminUser = Depends(require_editor)):
    note = db.query(CaseTeachingNote).filter(CaseTeachingNote.id == note_id).first()
    if not note:
        raise HTTPException(404, "Teaching note not found")
    db.delete(note)
    db.commit()


@router.put("/api/admin/teaching-notes/{note_id}/video", response_model=CaseTeachingNoteOut)
async def upload_teaching_note_video(note_id: str, db: Session = Depends(get_db),
                                      file: UploadFile = File(...),
                                      admin: AdminUser = Depends(require_editor)):
    note = db.query(CaseTeachingNote).filter(CaseTeachingNote.id == note_id).first()
    if not note:
        raise HTTPException(404, "Teaching note not found")
    raw = await file.read()
    try:
        video_bytes, content_type = process_video_upload(raw, file.content_type or "")
    except InvalidVideoError as exc:
        raise HTTPException(400, str(exc)) from exc
    note.video_data = video_bytes
    note.video_content_type = content_type
    note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(note)
    return _teaching_note_out(note)


@router.get("/api/teaching-notes/{note_id}/video")
def get_teaching_note_video(note_id: str, db: Session = Depends(get_db)):
    note = db.query(CaseTeachingNote).filter(CaseTeachingNote.id == note_id).first()
    if not note or not note.video_data:
        raise HTTPException(404, "No uploaded video")
    return Response(content=note.video_data, media_type=note.video_content_type or "video/mp4")


@router.post("/api/admin/teaching-notes/{note_id}/copy-to-archive", status_code=201)
def copy_teaching_note_to_archive(note_id: str, payload: CopyToArchiveIn, request: Request,
                                   db: Session = Depends(get_db), admin: AdminUser = Depends(require_editor)):
    """Reuses routers/archive.py::create_archive_entry directly -- the
    real Archive creation path (rate limiting, spam filtering, the
    hearing-must-have-already-happened check, attendee resolution), not a
    hand-rolled duplicate of it. This *copies* the note's content; the
    CaseTeachingNote row itself is untouched afterward. Fields with no
    real equivalent on a teaching note (attendees) are left for the
    Justice to fill in afterward on the new Archive entry directly,
    rather than guessed at here -- judge_name is filled from the
    hearing's own known judge_name when set, since that's real known
    data, not a guess."""
    note = db.query(CaseTeachingNote).filter(CaseTeachingNote.id == note_id).first()
    if not note:
        raise HTTPException(404, "Teaching note not found")
    hearing = db.query(Hearing).filter(Hearing.id == note.hearing_id).first()
    if not hearing:
        raise HTTPException(404, "This note's hearing no longer exists")

    archive_payload = ArchiveEntryIn(
        hearing_id=hearing.id,
        proceeding_stage=payload.proceeding_stage,
        judge_name=hearing.judge_name,
        reflection_text=note.body_text,
        submitted_by_name=admin.display_name or admin.email,
    )
    return create_archive_entry(archive_payload, request, db=db, justice=admin)
