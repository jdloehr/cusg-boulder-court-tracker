"""
app/jobs/digest.py::send_email -- the "console" default (used everywhere
in this test suite via monkeypatching) plus the real SendGrid backend
added so invite/reset/recommendation emails can actually be delivered.
"""
import logging

import httpx
import pytest

from app.jobs import digest


def test_console_backend_logs_and_does_not_raise(caplog):
    with caplog.at_level(logging.INFO):
        digest.send_email("someone@example.com", "Subject", "Body text")
    assert "someone@example.com" in caplog.text


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setattr(digest, "EMAIL_BACKEND", "carrier_pigeon")
    with pytest.raises(NotImplementedError):
        digest.send_email("someone@example.com", "Subject", "Body")


def test_sendgrid_without_config_logs_and_does_not_raise(monkeypatch, caplog):
    monkeypatch.setattr(digest, "EMAIL_BACKEND", "sendgrid")
    monkeypatch.setattr(digest, "SENDGRID_API_KEY", "")
    monkeypatch.setattr(digest, "EMAIL_FROM_ADDRESS", "")
    digest.send_email("someone@example.com", "Subject", "Body")
    assert "NOT sent" in caplog.text


def test_sendgrid_success_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(digest, "EMAIL_BACKEND", "sendgrid")
    monkeypatch.setattr(digest, "SENDGRID_API_KEY", "fake-key")
    monkeypatch.setattr(digest, "EMAIL_FROM_ADDRESS", "noreply@example.com")
    monkeypatch.setattr(digest, "EMAIL_FROM_NAME", "Test Sender")

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return httpx.Response(202, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    digest.send_email("justice@example.com", "You're invited", "Set your password here: ...")

    assert captured["url"] == "https://api.sendgrid.com/v3/mail/send"
    assert captured["headers"]["Authorization"] == "Bearer fake-key"
    assert captured["json"]["personalizations"] == [{"to": [{"email": "justice@example.com"}]}]
    assert captured["json"]["from"] == {"email": "noreply@example.com", "name": "Test Sender"}
    assert captured["json"]["subject"] == "You're invited"
    assert captured["json"]["content"] == [{"type": "text/plain", "value": "Set your password here: ..."}]


def test_sendgrid_error_response_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(digest, "EMAIL_BACKEND", "sendgrid")
    monkeypatch.setattr(digest, "SENDGRID_API_KEY", "fake-key")
    monkeypatch.setattr(digest, "EMAIL_FROM_ADDRESS", "noreply@example.com")

    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(401, text="Unauthorized", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    digest.send_email("justice@example.com", "Subject", "Body")  # must not raise
    assert "failed" in caplog.text


def test_sendgrid_network_error_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(digest, "EMAIL_BACKEND", "sendgrid")
    monkeypatch.setattr(digest, "SENDGRID_API_KEY", "fake-key")
    monkeypatch.setattr(digest, "EMAIL_FROM_ADDRESS", "noreply@example.com")

    def fake_post(*args, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", fake_post)
    digest.send_email("justice@example.com", "Subject", "Body")  # must not raise
    assert "raised" in caplog.text
