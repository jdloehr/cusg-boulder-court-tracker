"""
Phase-4 doc, Section 2.1: standard security headers on every response,
plus a real (not "*") CORS allow-list.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_security_headers_present_on_a_normal_response():
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "max-age=" in r.headers["Strict-Transport-Security"]
    assert r.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def test_cors_allows_the_known_frontend_origin():
    r = client.options(
        "/api/hearings",
        headers={
            "Origin": "https://cusg-boulder-court-tracker.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://cusg-boulder-court-tracker.vercel.app"


def test_cors_rejects_an_unrecognized_origin():
    r = client.options(
        "/api/hearings",
        headers={"Origin": "https://totally-unrelated-site.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}


# --- Oct 2026 review item 12 -------------------------------------------------

def test_cors_preflight_advertises_only_the_methods_actually_used():
    """Used to be "*" -- every router only ever registers GET/POST/PUT/
    PATCH/DELETE routes (confirmed by grepping every @router. decorator
    in app/routers/), so that's exactly what should come back, no more."""
    r = client.options(
        "/api/hearings",
        headers={
            "Origin": "https://cusg-boulder-court-tracker.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    allowed = {m.strip() for m in r.headers.get("access-control-allow-methods", "").split(",")}
    assert allowed == {"GET", "POST", "PUT", "PATCH", "DELETE"}


def test_cors_preflight_advertises_only_the_headers_actually_sent():
    """Used to be "*" -- frontend/src/api.js only ever sends
    Content-Type and Authorization, so those are the two names passed
    to allow_headers in app/main.py. Starlette's CORSMiddleware also
    always echoes back the four CORS-safelisted request headers
    (Accept, Accept-Language, Content-Language, Content-Type) on top of
    that regardless of configuration -- browsers send those
    automatically and a request containing *only* safelisted headers
    is "simple" (never preflighted) in the first place, so restricting
    them wouldn't narrow anything real; "authorization" is the one that
    actually reflects this app's own allow_headers setting."""
    r = client.options(
        "/api/hearings",
        headers={
            "Origin": "https://cusg-boulder-court-tracker.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type, Authorization",
        },
    )
    allowed = {h.strip().lower() for h in r.headers.get("access-control-allow-headers", "").split(",")}
    safelisted = {"accept", "accept-language", "content-language", "content-type"}
    assert allowed == safelisted | {"authorization"}


def test_cors_preflight_does_not_allow_an_unrecognized_header():
    r = client.options(
        "/api/hearings",
        headers={
            "Origin": "https://cusg-boulder-court-tracker.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Custom-Header",
        },
    )
    allowed = {h.strip().lower() for h in r.headers.get("access-control-allow-headers", "").split(",")}
    assert "x-custom-header" not in allowed


def test_cors_preflight_does_not_allow_an_unused_method():
    r = client.options(
        "/api/hearings",
        headers={
            "Origin": "https://cusg-boulder-court-tracker.vercel.app",
            "Access-Control-Request-Method": "TRACE",
        },
    )
    # Starlette's CORSMiddleware returns 400 for a preflight requesting
    # a method outside allow_methods, rather than reflecting it back.
    assert r.status_code == 400
