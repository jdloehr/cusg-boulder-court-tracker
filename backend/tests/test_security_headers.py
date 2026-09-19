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
