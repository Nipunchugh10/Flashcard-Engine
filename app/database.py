"""Database setup (SQLAlchemy + SQLite)."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,  # 30 seconds busy timeout
    } if _is_sqlite else {},
    # pool_pre_ping: on every checkout, send a lightweight ping to verify the
    # connection is still alive. Critical on PostgreSQL (Render) where idle
    # connections can be dropped by the DB or network layer between requests.
    pool_pre_ping=not _is_sqlite,
    echo=False,
)

@__import__("sqlalchemy").event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode for SQLite to allow concurrent reads and writes."""
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they don't already exist, then apply migrations."""
    from . import models  # noqa: F401 - register models on Base

    Base.metadata.create_all(bind=engine)
    _apply_migrations()


def _apply_migrations() -> None:
    """One-time schema migrations for columns added after initial release."""
    import logging

    log = logging.getLogger(__name__)
    migrations = [
        ("decks", "generation_status", "VARCHAR(20) DEFAULT 'ready'"),
        ("decks", "generation_error", "TEXT DEFAULT NULL"),
    ]
    with engine.connect() as conn:
        for table, column, col_def in migrations:
            try:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                    )
                )
                conn.commit()
                log.info("Migration: added %s.%s", table, column)
            except Exception:
                # Column already exists — that's fine.
                conn.rollback()
