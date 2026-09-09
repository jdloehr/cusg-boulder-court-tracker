#!/usr/bin/env python3
"""
Seeds the 7 real CUSG Supreme Court Justice accounts.

Generates a random password per justice and prints it ONCE to stdout --
nothing here gets written to a file that could end up committed to the
repo (unlike scripts/seed_demo_data.py's fictional demo accounts, these
are real people). Copy the printed passwords somewhere private (a
password manager, a DM) and hand each justice their own; there's no
password-reset flow yet, so re-run this script for one person at a time
(it skips anyone who already has an account) if someone needs a reset,
after first deleting their row.

Usage: python scripts/create_justices.py
"""
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import AdminUser  # noqa: E402

# (email, display_name, title). Email is just a login identifier here, not
# used for anything else (no email-sending to justices in this build) --
# adjust to real CU email addresses whenever the team has them.
JUSTICES = [
    ("dillon.rankin@cusg-justices.local", "Dillon Rankin", "Chief Justice"),
    ("avery.talbott@cusg-justices.local", "Avery Talbott", "Deputy Chief Justice"),
    ("joshua.loehr@cusg-justices.local", "Joshua Loehr", "Associate Justice"),
    ("fatimah.alshammari@cusg-justices.local", "Fatimah Al Shammari", "Associate Justice"),
    ("david.weinstein@cusg-justices.local", "David Weinstein", "Associate Justice"),
    ("maya.deferme@cusg-justices.local", "Maya Deferme", "Associate Justice"),
    ("townes.bakke@cusg-justices.local", "Townes Bakke", "Associate Justice"),
]


def main():
    init_db()
    db = SessionLocal()
    try:
        print("Justice accounts (save these passwords now -- they are not shown again):\n")
        for email, display_name, title in JUSTICES:
            if db.query(AdminUser).filter(AdminUser.email == email).first():
                print(f"  {display_name} ({email}) already exists, skipping")
                continue
            password = secrets.token_urlsafe(9)  # ~12 readable chars
            db.add(AdminUser(
                email=email,
                hashed_password=hash_password(password),
                is_justice=True,
                display_name=display_name,
                title=title,
            ))
            print(f"  {title} {display_name}\n    email: {email}\n    password: {password}\n")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
