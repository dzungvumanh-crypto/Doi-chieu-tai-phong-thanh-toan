"""DB-backed session store — thay thế in-memory dict."""
import sqlite3
from datetime import datetime, timedelta


def _utc_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def set_session(db: sqlite3.Connection, staff_id: int, ip: str, ttl_hours: int = 8) -> None:
    now = datetime.utcnow()
    expires_at = _utc_str(now + timedelta(hours=ttl_hours))
    db.execute(
        "INSERT OR REPLACE INTO login_sessions (staff_id, ip_address, expires_at) VALUES (?,?,?)",
        (staff_id, ip, expires_at),
    )
    # Dọn session hết hạn nhân tiện
    db.execute("DELETE FROM login_sessions WHERE expires_at < ?", (_utc_str(now),))


def get_session_ip(db: sqlite3.Connection, staff_id: int) -> str | None:
    now_str = _utc_str(datetime.utcnow())
    row = db.execute(
        "SELECT ip_address FROM login_sessions WHERE staff_id = ? AND expires_at > ?",
        (staff_id, now_str),
    ).fetchone()
    return row["ip_address"] if row else None


def clear_session(db: sqlite3.Connection, staff_id: int) -> None:
    db.execute("DELETE FROM login_sessions WHERE staff_id = ?", (staff_id,))
