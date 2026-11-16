from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import User


def main() -> None:
    users = [
        ("demo-admin", "DEMO_ADMIN_PASSWORD", "admin"),
        ("demo-analyst", "DEMO_ANALYST_PASSWORD", "analyst"),
        ("demo-approver", "DEMO_APPROVER_PASSWORD", "approver"),
        ("demo-auditor", "DEMO_AUDITOR_PASSWORD", "auditor"),
    ]
    missing = [env_name for _, env_name, _ in users if not os.getenv(env_name)]
    if missing:
        raise SystemExit(f"Missing password environment variables: {', '.join(missing)}")
    with SessionLocal() as db:
        for username, env_name, role in users:
            existing = db.scalar(select(User).where(User.username == username))
            if existing is None:
                db.add(User(username=username, password_hash=hash_password(os.environ[env_name]), role=role))
        db.commit()


if __name__ == "__main__":
    main()
