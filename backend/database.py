"""SQLite connection factory — raw SQL, no ORM."""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from backend.core.config import settings

DB_PATH = settings.DATABASE_URL.replace("sqlite:///", "")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

_VN_TZ = timezone(timedelta(hours=7))


def _vn_now() -> datetime:
    return datetime.now(_VN_TZ).replace(tzinfo=None)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
