from getpass import getpass

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.database.database import SessionLocal
from app.database.models.user import User


def create_admin():
    bootstrap_secret = getpass("Admin bootstrap secret: ")

    if bootstrap_secret != settings.ADMIN_BOOTSTRAP_SECRET:
        print("Invalid bootstrap secret.")
        return

    db = SessionLocal()

    try:
        existing_admin = db.execute(
            select(User).where(User.role == "ADMIN")
        ).scalar_one_or_none()

        if existing_admin is not None:
            print("An admin already exists.")
            return

        username = input("Admin username: ").strip()
        email = input("Admin email: ").strip()
        password = getpass("Admin password: ")

        existing_username = db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

        if existing_username is not None:
            print("Username already exists.")
            return

        existing_email = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if existing_email is not None:
            print("Email already exists.")
            return

        admin = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            role="ADMIN",
            status="ACTIVE"
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        print(f"Admin created successfully: {admin.username}")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    create_admin()