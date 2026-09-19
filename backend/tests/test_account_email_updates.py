"""
app/account_email_updates.py -- one-time Justice login-email updates,
driven by an env var (never a hardcoded mapping -- see that module's
docstring for why) so real people's real addresses never appear
literally in this repo, including in these tests.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account_email_updates import apply_email_updates, run_from_env
from app.auth import hash_password
from app.models import AdminRole, AdminUser, Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(AdminUser(email="placeholder1@example.local", hashed_password=hash_password("pw"),
                           is_justice=True, role=AdminRole.editor, display_name="Justice One"))
    session.add(AdminUser(email="placeholder2@example.local", hashed_password=hash_password("pw"),
                           is_justice=True, role=AdminRole.editor, display_name="Justice Two"))
    session.add(AdminUser(email="already-real@example.edu", hashed_password=hash_password("pw"),
                           is_justice=True, role=AdminRole.editor, display_name="Justice Three"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_updates_a_matching_account(db):
    applied = apply_email_updates(db, {"placeholder1@example.local": "real1@example.edu"})
    assert applied == ["placeholder1@example.local -> real1@example.edu"]
    user = db.query(AdminUser).filter(AdminUser.display_name == "Justice One").first()
    assert user.email == "real1@example.edu"


def test_preserves_password_and_role(db):
    apply_email_updates(db, {"placeholder1@example.local": "real1@example.edu"})
    user = db.query(AdminUser).filter(AdminUser.email == "real1@example.edu").first()
    from app.auth import verify_password
    assert verify_password("pw", user.hashed_password)
    assert user.role == AdminRole.editor
    assert user.is_justice is True


def test_running_twice_is_a_no_op_the_second_time(db):
    first = apply_email_updates(db, {"placeholder1@example.local": "real1@example.edu"})
    second = apply_email_updates(db, {"placeholder1@example.local": "real1@example.edu"})
    assert first == ["placeholder1@example.local -> real1@example.edu"]
    assert second == []


def test_skips_a_pair_with_no_matching_old_account(db):
    applied = apply_email_updates(db, {"nobody@example.local": "real@example.edu"})
    assert applied == []


def test_skips_when_the_new_email_is_already_taken(db):
    applied = apply_email_updates(db, {"placeholder1@example.local": "already-real@example.edu"})
    assert applied == []
    # the original account is untouched, not left half-updated
    user = db.query(AdminUser).filter(AdminUser.display_name == "Justice One").first()
    assert user.email == "placeholder1@example.local"


def test_handles_multiple_pairs_in_one_call(db):
    applied = apply_email_updates(db, {
        "placeholder1@example.local": "real1@example.edu",
        "placeholder2@example.local": "real2@example.edu",
    })
    assert set(applied) == {
        "placeholder1@example.local -> real1@example.edu",
        "placeholder2@example.local -> real2@example.edu",
    }


def test_run_from_env_does_nothing_when_unset(monkeypatch, db):
    monkeypatch.setattr("app.account_email_updates.JUSTICE_EMAIL_UPDATES", "")
    run_from_env(db.get_bind())  # must not raise
    user = db.query(AdminUser).filter(AdminUser.display_name == "Justice One").first()
    assert user.email == "placeholder1@example.local"


def test_run_from_env_applies_a_valid_json_mapping(monkeypatch, db):
    monkeypatch.setattr(
        "app.account_email_updates.JUSTICE_EMAIL_UPDATES",
        '{"placeholder1@example.local": "real1@example.edu"}',
    )
    run_from_env(db.get_bind())
    user = db.query(AdminUser).filter(AdminUser.display_name == "Justice One").first()
    assert user.email == "real1@example.edu"


def test_run_from_env_does_not_raise_on_invalid_json(monkeypatch, db):
    monkeypatch.setattr("app.account_email_updates.JUSTICE_EMAIL_UPDATES", "not valid json{")
    run_from_env(db.get_bind())  # must not raise
