"""Seed demo users using passwords supplied via environment variables.

Env vars (never hardcoded or printed):
- DEMO_ADMIN_PASSWORD     -> username: admin, role: admin
- DEMO_ANALYST_PASSWORD   -> username: analyst, role: analyst
- DEMO_APPROVER_PASSWORD  -> username: approver, role: approver
- DEMO_AUDITOR_PASSWORD   -> username: auditor, role: auditor
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.database import Base, SessionLocal, engine
from app.models import User
from app.services.audit import write_audit

DEMO_USER_SPECS: tuple[tuple[str, str, str], ...] = (
    ("admin", "admin", "DEMO_ADMIN_PASSWORD"),
    ("analyst", "analyst", "DEMO_ANALYST_PASSWORD"),
    ("approver", "approver", "DEMO_APPROVER_PASSWORD"),
    ("auditor", "auditor", "DEMO_AUDITOR_PASSWORD"),
)


def seed_demo_users(db: Session, env: dict[str, str] | None = None) -> dict[str, list[str]]:
    source = env if env is not None else dict(os.environ)
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    for username, role, env_var in DEMO_USER_SPECS:
        password = (source.get(env_var) or "").strip()
        if not password:
            skipped.append(f"{username} (set {env_var})")
            continue
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username, password_hash=hash_password(password), role=role)
            if hasattr(user, "status"):
                user.status = "active"
            if hasattr(user, "is_active"):
                user.is_active = True
            if hasattr(user, "created_via"):
                user.created_via = "seed"
            db.add(user)
            db.flush()
            created.append(f"{username} ({role})")
            action = "user_seeded"
        else:
            user.password_hash = hash_password(password)
            user.role = role
            if hasattr(user, "status"):
                user.status = "active"
            if hasattr(user, "is_active"):
                user.is_active = True
            updated.append(f"{username} ({role})")
            action = "user_seed_updated"
        write_audit(
            db,
            actor="seed_script",
            action=action,
            entity_type="User",
            entity_id=user.id,
            inputs={"username": username, "role": role, "source_env": env_var},
            formula="Seeded demo account from environment variable",
            output={"username": username, "role": role},
        )
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        result = seed_demo_users(db)
    print(f"Created: {', '.join(result['created']) or 'none'}")
    print(f"Updated: {', '.join(result['updated']) or 'none'}")
    print(f"Skipped: {', '.join(result['skipped']) or 'none'}")


if __name__ == "__main__":
    main()
