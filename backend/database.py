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


def write_audit(
    db: sqlite3.Connection,
    actor_id: int,
    action: str,
    target_type: str = None,
    target_id: int = None,
    detail: str = None,
    ip: str = None,
) -> None:
    db.execute(
        "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, ip_address, created_at) VALUES (?,?,?,?,?,?,?)",
        (actor_id, action, target_type, target_id, detail, ip, _vn_now()),
    )


def compute_annual_leave(join_date_str, year: int = None) -> int:
    """Tính số ngày phép năm: 12 ngày + 1 ngày mỗi 4 năm vào ngành.

    Ví dụ: vào ngành 2007, năm 2011 → 13 ngày; năm 2015 → 14 ngày.
    Trả về 12 nếu join_date_str là None hoặc không hợp lệ.
    """
    if not join_date_str:
        return 12
    from datetime import date
    try:
        join_date = join_date_str if isinstance(join_date_str, date) else date.fromisoformat(str(join_date_str))
        ref_year = year or date.today().year
        years = ref_year - join_date.year
        return 12 + max(0, years // 4)
    except Exception:
        return 12


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
