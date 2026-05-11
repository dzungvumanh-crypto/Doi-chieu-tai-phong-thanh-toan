"""SQLAlchemy database setup"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from backend.core.config import settings
import os

os.makedirs(os.path.dirname(settings.DATABASE_URL.replace("sqlite:///", "")), exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,        # Chờ tối đa 30s khi DB bị lock ở tầng SQLAlchemy
    },
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(conn, _):
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30s — tầng SQLite
    conn.execute("PRAGMA synchronous=NORMAL")  # An toàn với WAL, giảm I/O


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
