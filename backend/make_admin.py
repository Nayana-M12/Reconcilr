from sqlalchemy import select
from app.database import SessionLocal
from app.auth import hash_password
from app.models.entities import User

USERNAME = "admin"
PASSWORD = "ChangeMe-12345"  # at least 12 characters

with SessionLocal() as db:
    user = db.scalar(select(User).where(User.username == USERNAME))
    if user:
        user.password_hash = hash_password(PASSWORD)
        print("Password reset for", USERNAME)
    else:
        db.add(User(username=USERNAME, password_hash=hash_password(PASSWORD), role="admin"))
        print("Created admin user", USERNAME)
    db.commit()