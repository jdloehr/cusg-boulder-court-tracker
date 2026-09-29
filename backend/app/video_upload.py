"""
Phase 9 doc: video-upload validation for LearnTopic/CaseTeachingNote.

Reuses app/photo.py's exact storage convention -- Postgres BYTEA on the
row itself, no separate object-storage service, since this project has
none provisioned (confirmed by checking render.yaml/docs/DEPLOYMENT.md
before assuming: Render web service + Render Postgres, nothing else).
That choice is a much easier call for a handful of small profile photos
than it is for video, though, so this is a real, deliberate departure
from photo.py in two ways -- both called out here rather than silently
copied over:

1. No re-encoding. photo.py's real validation is "Pillow can actually
   decode this" (a renamed non-image file fails to open), not the
   declared Content-Type. Pillow cannot decode video, and this project
   has no ffmpeg dependency -- adding one just for this feature's
   optional upload path (pasting a URL already covers the same need) is
   a heavier infrastructure commitment than this project's scale calls
   for. Validation here is therefore weaker: a declared-Content-Type
   allowlist plus a real header-bytes sniff (see _sniff_container below)
   for the handful of common formats, not full decode-and-validate.
2. A much tighter size cap than a photo's 5MB, but not so tight that it
   defeats the feature -- an explainer genuinely needs a few minutes, not
   seconds. 100MB comfortably covers a 3-5 minute clip at a reasonable
   720p bitrate (~2.5-4 Mbps) with room for a less-efficient phone-camera
   encode, not just a 15-20 second clip. This is a real, explicit
   tradeoff against Render's free-tier Postgres storage plan, which is
   small (order of 1GB) and shared with every other table in this
   database -- a handful of uploaded videos at this cap is a meaningful
   fraction of that. Accepted anyway because a teaching video that's too
   short to actually explain anything isn't a real feature; pasting a
   YouTube/Vimeo/direct-file URL (no size limit, no server storage at
   all) remains the better path for anything longer than a few minutes,
   and the UI says so. If upload volume ever becomes real, the fix is a
   real object-storage service (S3-compatible), not a smaller cap.
"""
from __future__ import annotations

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB -- see module docstring point 2
ALLOWED_CONTENT_TYPES = {"video/mp4", "video/webm", "video/ogg", "video/quicktime"}

# Minimal container-format sniffing -- not a full decode (see module
# docstring point 1), but enough to catch "this isn't actually a video
# file" the same way photo.py's Pillow-decode catches a mislabeled image.
# Checked against the byte ranges these formats are documented to start
# with; a container format not listed here (e.g. an obscure codec inside
# an MP4-like box) may still fail this even though it decodes fine in a
# real player -- an acceptable false-negative for a feature whose real
# fallback (paste a URL) has no such limitation.
_MP4_BRANDS = (b"ftyp",)
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
_OGG_MAGIC = b"OggS"


class InvalidVideoError(ValueError):
    """Raised for any upload that fails validation -- callers turn this
    into an HTTP 400 with the message as-is."""


def _sniff_container(raw_bytes: bytes, declared_content_type: str) -> bool:
    head = raw_bytes[:64]
    if declared_content_type == "video/webm":
        return head.startswith(_WEBM_MAGIC)
    if declared_content_type == "video/ogg":
        return head.startswith(_OGG_MAGIC)
    # video/mp4 and video/quicktime (.mov) are both ISO base media file
    # format containers -- an "ftyp" box a few bytes into the file, not
    # necessarily at byte 0 (a leading size-only box can precede it).
    return b"ftyp" in head


def process_video_upload(raw_bytes: bytes, declared_content_type: str) -> tuple[bytes, str]:
    """Validates an uploaded video. Returns (raw_bytes, content_type) on
    success -- unlike process_profile_photo, the bytes are stored as-is,
    not re-encoded (see module docstring). Raises InvalidVideoError
    otherwise."""
    if declared_content_type not in ALLOWED_CONTENT_TYPES:
        raise InvalidVideoError(
            f"Unsupported file type {declared_content_type!r} -- upload an MP4, WebM, Ogg, or MOV video"
        )
    if not raw_bytes:
        raise InvalidVideoError("Empty file")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise InvalidVideoError(
            f"File too large -- max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB. "
            "For a longer video, paste a YouTube/Vimeo/direct-file link instead."
        )
    if not _sniff_container(raw_bytes, declared_content_type):
        raise InvalidVideoError("File isn't a valid video of the declared type (or is corrupted)")

    return raw_bytes, declared_content_type
