"""
Phase-2 doc, Section 6: "Rate-limit all public write endpoints (summary
submission, manual refresh) per IP." A simple in-process sliding-window
counter -- correct and sufficient for a single-instance deployment (this
project's actual scale, per Section 7's "any transactional provider's free
tier is almost certainly sufficient" framing), but it resets on restart
and doesn't share state across multiple instances/workers. A multi-
instance deployment would need a shared store (Redis, etc.) behind the
same `check_rate_limit()` signature -- documented here rather than
silently assumed away, see docs/SECURITY_REVIEW.md.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config import TRUSTED_PROXY_HOPS

_hits: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Returns True if this call is allowed, False if `key` has already
    made `max_requests` calls within the trailing `window_seconds`."""
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= max_requests:
        return False
    q.append(now)
    return True


def reset_for_tests() -> None:
    """The module-level `_hits` dict persists for the life of the Python
    process, which is exactly right in production (one process, real
    per-visitor IPs) but leaks across test functions that all share the
    same TestClient "IP" -- without this, an early test's requests count
    against a later test's rate-limit budget. Call from a fixture, not
    production code."""
    _hits.clear()


def client_ip(request) -> str:
    """Best-effort client IP -- checks X-Forwarded-For first since Render
    (like most PaaS hosts) sits behind a proxy, where request.client.host
    would otherwise just be the proxy's own address.

    Real bug, Oct 2026 review item 3: this used to return the *first*
    entry in X-Forwarded-For, which is entirely attacker-controlled --
    anyone can send their own `X-Forwarded-For: 1.2.3.4` and every rate
    limit keyed on this function (login, subscribe, refresh, ...) would
    key off that spoofed value, making the limit bypassable by just
    rotating the fake value per request. The header's real shape, left
    to right, is "whatever the client sent (0 or more spoofed entries),
    then one entry appended by each real proxy the request actually
    passed through" -- each proxy appends the address it saw the
    request arrive from, so the LAST TRUSTED_PROXY_HOPS entries (not the
    first one) are the ones no client-side spoofing can touch, and the
    real client IP is exactly TRUSTED_PROXY_HOPS entries from the right
    (Render is one proxy hop, hence the default of 1). If the header has
    fewer entries than that -- malformed, or this process somehow
    received a request that didn't pass through every expected proxy --
    there's nothing trustworthy to extract from it, so this falls back
    to request.client.host (the immediate TCP peer) instead of guessing
    which entry is real."""
    forwarded = request.headers.get("x-forwarded-for")
    direct = request.client.host if request.client else "unknown"
    if not forwarded:
        return direct
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if len(parts) < TRUSTED_PROXY_HOPS:
        return direct
    return parts[-TRUSTED_PROXY_HOPS]
