from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.models import Base

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create tables if they don't exist. For local SQLite dev/demo use.
    Production against Postgres should use a real migration tool
    (Alembic) instead of create_all -- see docs/ARCHITECTURE.md.

    Runs app.migrations.run_startup_migrations() right after, to cover
    what create_all() can't: ALTERing a table that already exists. See
    that module's docstring -- this project's Render plan has no Shell/
    one-off-job access, so a schema patch that isn't automatic at boot
    doesn't have anywhere to run at all.

    Also runs app.account_email_updates.run_from_env() -- same "no Shell
    access" reasoning, but for one-time Justice login-email updates
    driven by an env var instead of a schema change."""
    Base.metadata.create_all(bind=engine)
    from app.migrations import run_startup_migrations
    run_startup_migrations(engine)
    from app.account_email_updates import run_from_env
    run_from_env(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
