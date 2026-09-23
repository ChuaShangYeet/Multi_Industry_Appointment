"""
One-off script that creates the first SuperAdmin account, so there's a way
into the admin API on a brand-new database. Run with:

    python -m app.bootstrap_admin

Reads FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD from the environment (.env) -
change the password immediately after first login via
PATCH /api/v1/admin/customers isn't applicable here; use the admin's own
password-reset endpoint you build on top of this, or update the DB row
directly for now.
"""
import app.models  # noqa: F401 - ensure every table is registered on Base.metadata
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.enums import AdminRoleLevel
from app.models.admin import AdminUser
from app.security import hash_password


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(AdminUser).filter(AdminUser.email == settings.FIRST_ADMIN_EMAIL).first()
        if existing:
            print(f"Admin '{settings.FIRST_ADMIN_EMAIL}' already exists (id={existing.id}). Nothing to do.")
            return

        admin = AdminUser(
            email=settings.FIRST_ADMIN_EMAIL,
            password_hash=hash_password(settings.FIRST_ADMIN_PASSWORD),
            role_level=AdminRoleLevel.SUPER_ADMIN,
            first_name="Super",
            last_name="Admin",
        )
        db.add(admin)
        db.commit()
        print(f"Created SuperAdmin '{admin.email}'.")
        print(f"Log in via POST {settings.API_V1_PREFIX}/auth/admin/login")
    finally:
        db.close()


if __name__ == "__main__":
    main()
