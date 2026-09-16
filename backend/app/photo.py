"""
Phase-3 doc, Section 3 & 5: Justice profile photo processing.

Section 5's requirement ("validate file type/size and strip metadata
before storing/serving") is met like this:
- File type: Pillow actually opens and decodes the upload -- a renamed
  non-image file (e.g. a .exe with a .jpg extension) fails to open rather
  than being trusted from its declared Content-Type or extension.
- Size: checked twice -- the raw upload against MAX_UPLOAD_BYTES before
  decoding anything (so a huge file doesn't even get handed to Pillow),
  and the final re-encoded image is capped to MAX_DIMENSION on its long
  edge.
- Metadata: every upload gets re-encoded to a fresh JPEG. Pillow's
  default save() does not carry over the source file's EXIF/ICC/XMP
  blocks unless you explicitly pass them back in -- this code doesn't --
  so metadata (including GPS location, if a phone camera embedded one)
  is stripped simply by virtue of not being copied to the new file, not
  by a separate "now strip metadata" step.

Always re-encodes to JPEG regardless of the input format (PNG, WEBP) --
one format to store and serve keeps GET /api/justices/{id}/photo simple,
and a small headshot photo has no real need for PNG's transparency or
lossless encoding anyway.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB raw upload cap, checked before decoding
MAX_DIMENSION = 800  # long-edge cap on the re-encoded image, in pixels
JPEG_QUALITY = 85
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class InvalidPhotoError(ValueError):
    """Raised for any upload that fails validation -- callers turn this
    into an HTTP 400 with the message as-is."""


def process_profile_photo(raw_bytes: bytes, declared_content_type: str) -> tuple[bytes, str]:
    """Validates and re-encodes an uploaded profile photo. Returns
    (jpeg_bytes, "image/jpeg") on success; raises InvalidPhotoError
    otherwise. `declared_content_type` is the client's Content-Type
    header -- a first, cheap filter, but never trusted alone (see the
    Pillow-decode check below, which is the real validation)."""
    if declared_content_type not in ALLOWED_CONTENT_TYPES:
        raise InvalidPhotoError(
            f"Unsupported file type {declared_content_type!r} -- upload a JPEG, PNG, or WEBP image"
        )
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise InvalidPhotoError(f"File too large -- max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
    if not raw_bytes:
        raise InvalidPhotoError("Empty file")

    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()  # forces full decode now, while we can still raise cleanly
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidPhotoError("File isn't a valid image (or is corrupted)") from exc

    # Apply any EXIF orientation tag (phone photos are frequently stored
    # "sideways" with a rotation flag) before that tag gets dropped by
    # re-encoding, so the photo doesn't come out rotated.
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")  # drops alpha/palette; JPEG has no transparency anyway

    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue(), "image/jpeg"
