"""
Phase-2 doc, Section 5/6: "Basic automated spam/profanity filtering on
submission" for the Archive's public "Submit a Summary" path, which
(unlike CommunitySubmission) publishes immediately with no human review
queue -- this is the automated first line of defense that trade-off needs,
not a replacement for the after-the-fact safeguards (submitter IP logging,
Justice edit/remove) documented on ArchiveEntry itself.

Deliberately simple and named as such: a real, working word-list-based
filter plus a couple of cheap spam heuristics, not a machine-learning
classifier. Good enough to catch the obvious cases; a determined bad actor
could get past this, which is exactly why the after-the-fact safeguards
exist too.
"""
from __future__ import annotations

import re

# Intentionally short and conservative -- this is a first-pass filter, not
# the only safeguard (see module docstring). Extend as real abuse patterns
# show up; over-blocking a genuine reflection is worse than under-blocking
# spam here, since there's a human (any Justice) who can still remove a
# bad one after the fact.
_BLOCKED_SUBSTRINGS = [
    "viagra", "cialis", "casino", "porn", "xxx",
    "fuck", "shit", "asshole", "bitch", "cunt",
]

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def is_likely_spam_or_profane(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(word in lowered for word in _BLOCKED_SUBSTRINGS):
        return True
    # More than a couple of links in a short reflection reads as spam, not
    # a genuine court write-up.
    if len(_URL_RE.findall(text)) > 2:
        return True
    # A single character (or very short run) repeated well past anything
    # a real sentence would produce -- "aaaaaaaaaaaaaaaa" style filler.
    if re.search(r"(.)\1{9,}", text):
        return True
    return False
