"""DB-backed rate limiter cho login endpoint."""
import sqlite3
from datetime import datetime, timedelta

MAX_FAILURES = 5
WINDOW = timedelta(minutes=5)
LOCKOUT = timedelta(minutes=15)


def _utc_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def seconds_locked(db: sqlite3.Connection, username: str) -> int:
    now = datetime.utcnow()
    row = db.execute(
        "SELECT locked_until FROM login_rate_limit WHERE username = ?", (username,)
    ).fetchone()
    if not row or not row["locked_until"]:
        return 0
    if _utc_str(now) < row["locked_until"]:
        lu = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S")
        return max(1, int((lu - now).total_seconds()))
    return 0


def record_failed(db: sqlite3.Connection, username: str) -> None:
    now = datetime.utcnow()
    row = db.execute(
        "SELECT attempt_count, window_start FROM login_rate_limit WHERE username = ?", (username,)
    ).fetchone()

    # Còn trong cửa sổ thời gian?
    in_window = False
    if row and row["window_start"]:
        ws = datetime.strptime(row["window_start"], "%Y-%m-%d %H:%M:%S")
        in_window = (now - ws) <= WINDOW

    if not in_window:
        db.execute(
            "INSERT OR REPLACE INTO login_rate_limit (username, attempt_count, window_start, locked_until) VALUES (?,?,?,NULL)",
            (username, 1, _utc_str(now)),
        )
    else:
        new_count = (row["attempt_count"] or 0) + 1
        locked_until = _utc_str(now + LOCKOUT) if new_count >= MAX_FAILURES else None
        db.execute(
            "UPDATE login_rate_limit SET attempt_count = ?, locked_until = ? WHERE username = ?",
            (new_count, locked_until, username),
        )


def clear(db: sqlite3.Connection, username: str) -> None:
    db.execute("DELETE FROM login_rate_limit WHERE username = ?", (username,))
