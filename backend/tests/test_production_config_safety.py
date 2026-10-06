"""
Oct 2026 review item 8: app/config.py refuses to import at all (and so
the app refuses to boot) when ENVIRONMENT=production but JWT_SECRET or
GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY are still their committed
placeholder defaults -- both are public (this is an open source tree),
so leaving either one unset in a real deployment would let anyone forge
a valid admin JWT, or decrypt any stored Google Calendar refresh token.

app/config.py runs this check at module import time, not inside a
function -- these tests reload the module under different env vars to
exercise it, and always reload it back to a clean state afterward (see
reload_config's teardown) since Python caches modules process-wide, and
every other test in the suite does `from app.config import X` and would
otherwise see whatever the last reload here left behind.
"""
import importlib

import pytest

import app.config as config_module


@pytest.fixture()
def reload_config(monkeypatch):
    env_keys = ["ENVIRONMENT", "JWT_SECRET", "GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY", "ALLOWED_ORIGINS"]

    def _reload(**env):
        for key in env_keys:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config_module)

    yield _reload

    # Restore the real module state for every test that runs after this
    # one -- see the module docstring above for why this matters.
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)
    importlib.reload(config_module)


def test_production_with_default_jwt_secret_refuses_to_boot(reload_config):
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        reload_config(ENVIRONMENT="production", GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY="a-real-fernet-key")


def test_production_with_default_google_calendar_key_refuses_to_boot(reload_config):
    with pytest.raises(RuntimeError, match="GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY"):
        reload_config(ENVIRONMENT="production", JWT_SECRET="a-real-secret")


def test_production_with_both_still_default_names_both_in_the_error(reload_config):
    with pytest.raises(RuntimeError) as exc_info:
        reload_config(ENVIRONMENT="production")
    assert "JWT_SECRET" in str(exc_info.value)
    assert "GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY" in str(exc_info.value)


def test_production_with_both_overridden_boots_fine(reload_config):
    mod = reload_config(
        ENVIRONMENT="production", JWT_SECRET="a-real-secret",
        GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY="a-real-fernet-key",
    )
    assert mod.ENVIRONMENT == "production"
    assert mod.JWT_SECRET == "a-real-secret"


def test_development_with_default_values_boots_fine(reload_config):
    """The whole point of gating this on ENVIRONMENT=production --
    local dev (and CI) never sets it, so the placeholders stay usable
    there without any extra setup."""
    mod = reload_config(ENVIRONMENT="development")
    assert mod.JWT_SECRET == mod._JWT_SECRET_DEV_DEFAULT
    assert mod.GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY == mod._GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY_DEV_DEFAULT


# --- Oct 2026 review item 12 -------------------------------------------------

def test_default_allowed_origins_drops_localhost_in_production(reload_config):
    mod = reload_config(ENVIRONMENT="production", JWT_SECRET="x", GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY="y")
    assert mod.ALLOWED_ORIGINS == ["https://cusg-boulder-court-tracker.vercel.app"]


def test_default_allowed_origins_keeps_localhost_outside_production(reload_config):
    mod = reload_config(ENVIRONMENT="development")
    assert "http://localhost:5173" in mod.ALLOWED_ORIGINS
    assert "http://localhost:3000" in mod.ALLOWED_ORIGINS


def test_explicit_allowed_origins_env_var_always_wins(reload_config):
    """An operator-set ALLOWED_ORIGINS is respected exactly as given,
    regardless of ENVIRONMENT -- only the *default* (no env var at all)
    depends on it."""
    mod = reload_config(
        ENVIRONMENT="production", JWT_SECRET="x", GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY="y",
        ALLOWED_ORIGINS="https://custom.example,http://localhost:5173",
    )
    assert mod.ALLOWED_ORIGINS == ["https://custom.example", "http://localhost:5173"]
