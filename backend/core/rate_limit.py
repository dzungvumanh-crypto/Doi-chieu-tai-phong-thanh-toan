"""In-memory rate limiter cho login endpoint."""
from datetime import datetime, timedelta
from threading import Lock

_attempts: dict = {}  # username → {"count": int, "window_start": datetime, "locked_until": datetime|None}
_lock = Lock()

MAX_FAILURES = 5        # số lần sai tối đa trong cửa sổ
WINDOW = timedelta(minutes=5)   # cửa sổ đếm
LOCKOUT = timedelta(minutes=15) # thời gian khóa


def seconds_locked(username: str) -> int:
    """Trả về số giây còn bị khóa; 0 nếu không bị khóa."""
    now = datetime.utcnow()
    with _lock:
        rec = _attempts.get(username)
        if not rec:
            return 0
        lu = rec.get("locked_until")
        if lu and now < lu:
            return max(1, int((lu - now).total_seconds()))
        return 0


def record_failed(username: str) -> None:
    """Ghi nhận 1 lần đăng nhập sai; khóa tài khoản nếu vượt ngưỡng."""
    now = datetime.utcnow()
    with _lock:
        rec = _attempts.get(username)
        # Reset nếu cửa sổ đã hết
        if rec and now - rec["window_start"] > WINDOW:
            rec = None
        if rec is None:
            _attempts[username] = {"count": 1, "window_start": now, "locked_until": None}
            return
        rec["count"] += 1
        if rec["count"] >= MAX_FAILURES:
            rec["locked_until"] = now + LOCKOUT


def clear(username: str) -> None:
    """Xóa record sau khi đăng nhập thành công."""
    with _lock:
        _attempts.pop(username, None)
