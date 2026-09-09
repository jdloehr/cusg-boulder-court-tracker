#!/usr/bin/env python3
"""Bootstrap an AdminUser (Section 5.4). Run once per new team member.

Usage: python scripts/create_admin_user.py editor@cusg.colorado.edu editor
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import AdminRole, AdminUser  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("Usage: create_admin_user.py <email> <editor|contributor> [password]")
        sys.exit(1)

    email, role_str = sys.argv[1], sys.argv[2]
    password = sys.argv[3] if len(sys.argv) > 3 else "changeme"
    role = AdminRole(role_str)

    init_db()
    db = SessionLocal()
    try:
        if db.query(AdminUser).filter(AdminUser.email == email).first():
            print(f"{email} already exists")
            sys.exit(1)
        user = AdminUser(email=email, hashed_password=hash_password(password), role=role)
        db.add(user)
        db.commit()
        print(f"Created {role.value} {email} with password {password!r} -- change it on first login "
              f"(no password-change endpoint exists yet; re-run this script to reset for now).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
