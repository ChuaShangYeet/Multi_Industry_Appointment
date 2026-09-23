"""
SQLAlchemy engine/session setup.

Works out of the box against SQLite (zero-setup local dev) and Postgres
(recommended for anything beyond a single developer's laptop) - just swap
DATABASE_URL in .env. Nothing in the models or routers is SQLite/Postgres
specific.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
