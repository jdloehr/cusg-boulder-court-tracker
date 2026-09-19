"""
Phase-4 doc, Section 2.1: standard security response headers, applied to
every backend response. HTTPS itself is already enforced by Render (the
platform terminates TLS and Render's own docs confirm certs auto-renew --
nothing for this app's own code to configure); this middleware covers
what actually is this app's responsibility.

This is an API that returns JSON almost everywhere (the two exceptions --
the .ics calendar export and, when enabled, the interactive docs UI --
are plain-text/HTML respectively, and get the same headers), so a fairly
locked-down baseline CSP is safe: nothing here needs to load scripts,
styles, or frames from anywhere. The frontend (a separate origin on
Vercel) has its own, less restrictive CSP for actually rendering the
site -- see frontend/vercel.json.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# No inline/external scripts, styles, or frames needed for a JSON API
# (or the one PlainTextResponse endpoint, the .ics export) -- 'none'
# everywhere is correct, not just cautious.
API_CSP = "; ".join([
    "default-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'none'",
])


# FastAPI's own interactive docs (disabled in production -- see
# ENVIRONMENT in app/config.py/app/main.py -- but still handy in local
# dev) load their JS/CSS from a CDN, which the locked-down API_CSP above
# would block. Exempted from that one header rather than loosening it for
# every response just to accommodate a dev-only page.
_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # HSTS only means anything over HTTPS -- harmless to send always,
        # since Render serves this app over HTTPS exclusively.
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path not in _DOCS_PATHS:
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        return response
