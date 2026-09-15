from app.rate_limit import check_rate_limit, reset_for_tests


def setup_function():
    reset_for_tests()


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
