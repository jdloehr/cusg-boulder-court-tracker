from app.rate_limit import check_rate_limit, client_ip, reset_for_tests


def setup_function():
    reset_for_tests()


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Minimal stand-in for fastapi.Request -- client_ip only ever reads
    .headers.get(...) and .client.host."""
    def __init__(self, headers=None, client_host="203.0.113.9"):
        self.headers = headers or {}
        self.client = _FakeClient(client_host) if client_host else None


def test_client_ip_falls_back_to_direct_peer_with_no_forwarded_header():
    assert client_ip(_FakeRequest(client_host="198.51.100.1")) == "198.51.100.1"


def test_client_ip_uses_the_rightmost_entry_not_the_spoofable_leftmost_one():
    """Oct 2026 review item 3: the real bug this closes -- a client can
    put anything at all in X-Forwarded-For; only what Render's own
    proxy appends (the rightmost entry, with TRUSTED_PROXY_HOPS=1) can't
    be spoofed by the client sending the request."""
    req = _FakeRequest(headers={"x-forwarded-for": "9.9.9.9, 203.0.113.9"})
    assert client_ip(req) == "203.0.113.9"
    assert client_ip(req) != "9.9.9.9"


def test_client_ip_handles_multiple_spoofed_leading_entries(monkeypatch):
    import app.rate_limit as rate_limit_module
    monkeypatch.setattr(rate_limit_module, "TRUSTED_PROXY_HOPS", 1)
    req = _FakeRequest(headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2, 3.3.3.3, 203.0.113.9"})
    assert client_ip(req) == "203.0.113.9"


def test_client_ip_respects_a_configured_second_trusted_hop(monkeypatch):
    """A future deployment with two trusted proxies in front of this app
    (e.g. a CDN in front of Render) would set TRUSTED_PROXY_HOPS=2 --
    the real client IP then sits two entries from the right, not one."""
    import app.rate_limit as rate_limit_module
    monkeypatch.setattr(rate_limit_module, "TRUSTED_PROXY_HOPS", 2)
    req = _FakeRequest(headers={"x-forwarded-for": "9.9.9.9, 203.0.113.9, 192.0.2.1"})
    assert client_ip(req) == "203.0.113.9"


def test_client_ip_falls_back_to_direct_peer_when_header_has_too_few_entries(monkeypatch):
    """Fewer X-Forwarded-For entries than TRUSTED_PROXY_HOPS means
    there's nothing trustworthy to extract -- falls back to the
    immediate TCP peer rather than guessing."""
    import app.rate_limit as rate_limit_module
    monkeypatch.setattr(rate_limit_module, "TRUSTED_PROXY_HOPS", 2)
    req = _FakeRequest(headers={"x-forwarded-for": "9.9.9.9"}, client_host="203.0.113.9")
    assert client_ip(req) == "203.0.113.9"


def test_allows_up_to_the_limit_then_blocks():
    for _ in range(5):
        assert check_rate_limit("k", max_requests=5, window_seconds=60) is True
    assert check_rate_limit("k", max_requests=5, window_seconds=60) is False


def test_different_keys_have_independent_budgets():
    for _ in range(5):
        assert check_rate_limit("a", max_requests=5, window_seconds=60) is True
    # "a" is now exhausted, but "b" hasn't made any requests yet
    assert check_rate_limit("b", max_requests=5, window_seconds=60) is True


def test_old_hits_age_out_of_the_window():
    assert check_rate_limit("k", max_requests=1, window_seconds=0) is True
    # window_seconds=0 means the previous hit is immediately stale
    assert check_rate_limit("k", max_requests=1, window_seconds=0) is True
