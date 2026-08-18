"""Giới hạn số lần đăng nhập sai — theo TÊN ĐĂNG NHẬP và theo ĐỊA CHỈ MÁY.

Chỉ đếm theo tên đăng nhập là hở một lối: kẻ dò chỉ cần đổi tên đăng nhập sau
mỗi 4 lần thử là chạy mãi không bị chặn — thử một mật khẩu phổ biến lần lượt
trên cả 78 tài khoản (kiểu tấn công "rải mật khẩu") không hề chạm ngưỡng nào.

Nên đếm thêm theo địa chỉ máy gọi tới, ngưỡng rộng hơn (một phòng dùng chung
một địa chỉ ra ngoài thì vài người gõ nhầm cùng lúc là chuyện thường).

Hai bộ đếm dùng chung bảng `login_rate_limit`: khoá của bộ đếm theo máy là
chuỗi "ip:<địa_chỉ>" — cột `username` là TEXT PRIMARY KEY nên không đụng tên
đăng nhập thật (tên đăng nhập không chứa dấu hai chấm) và không cần migration.

Còn tồn tại (biết mà chưa xử): khoá theo tên đăng nhập vẫn cho phép một người
cố tình khoá tài khoản của người khác 15 phút bằng 5 lần gõ sai. Bỏ luật đó đi
thì mất lớp chống dò vào một tài khoản cụ thể — đánh đổi này cần quyết định về
nghiệp vụ (vd. chỉ khoá theo cặp tên+máy), không tự ý đổi ở đây.
"""
import sqlite3
from datetime import datetime, timedelta

MAX_FAILURES = 5
WINDOW = timedelta(minutes=5)
LOCKOUT = timedelta(minutes=15)

# Ngưỡng cho địa chỉ máy — cao hơn vì nhiều người có thể dùng chung một địa chỉ.
MAX_FAILURES_IP = 20
LOCKOUT_IP = timedelta(minutes=15)

_TIEN_TO_IP = "ip:"


def khoa_theo_ip(ip: str) -> str:
    return f"{_TIEN_TO_IP}{ip}"


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


def record_failed(db: sqlite3.Connection, username: str, max_failures: int = MAX_FAILURES,
                  lockout: timedelta = LOCKOUT) -> None:
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
        locked_until = _utc_str(now + lockout) if new_count >= max_failures else None
        db.execute(
            "UPDATE login_rate_limit SET attempt_count = ?, locked_until = ? WHERE username = ?",
            (new_count, locked_until, username),
        )


def clear(db: sqlite3.Connection, username: str) -> None:
    db.execute("DELETE FROM login_rate_limit WHERE username = ?", (username,))


# ── Bọc sẵn cho endpoint đăng nhập ───────────────────────────────────────────

def seconds_locked_any(db: sqlite3.Connection, username: str, ip: str) -> int:
    """Thời gian còn bị khoá, lấy giá trị LỚN HƠN giữa khoá theo tên và theo máy."""
    return max(seconds_locked(db, username), seconds_locked(db, khoa_theo_ip(ip)))


def record_failed_any(db: sqlite3.Connection, username: str, ip: str) -> None:
    """Đếm một lần sai cho cả hai bộ đếm."""
    record_failed(db, username)
    record_failed(db, khoa_theo_ip(ip), MAX_FAILURES_IP, LOCKOUT_IP)


def clear_any(db: sqlite3.Connection, username: str, ip: str) -> None:
    """Đăng nhập đúng → xoá cả hai bộ đếm."""
    clear(db, username)
    clear(db, khoa_theo_ip(ip))
