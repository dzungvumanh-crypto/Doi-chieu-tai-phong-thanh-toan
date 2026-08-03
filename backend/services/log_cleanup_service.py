"""Dọn nhật ký cũ theo lịch — login_logs và audit_logs.

Trước đây việc dọn nằm ngay trong endpoint xem nhật ký: không admin nào mở màn
hình đó thì bảng phình vô hạn (audit_logs nhận 1 dòng cho MỖI thao tác ghi của
MỖI người dùng), rồi đến khi có người mở thì một lệnh DELETE khổng lồ chạy giữa
request và giữ khoá ghi rất lâu — đúng lúc đó mọi request ghi khác đều phải chờ.

Tách ra chạy nền: dọn đều đặn nên mỗi lần xoá ít, và không nằm trên đường đi của
request nào cả.
"""
import logging
import sqlite3
import threading
from datetime import datetime, timedelta

_log = logging.getLogger(__name__)

LOGIN_RETENTION_DAYS = 30
AUDIT_RETENTION_DAYS = 365
_INTERVAL_HOURS = 12

# Ref timer toàn cục để có thể hủy khi test
_timer: threading.Timer | None = None


def run_cleanup(db_path: str = "data/ksnb.db") -> dict:
    """Xoá nhật ký quá hạn. Trả về số dòng đã xoá theo từng bảng."""
    deleted = {"login_logs": 0, "audit_logs": 0}
    now = datetime.utcnow()
    # Chờ khoá ngắn thôi: đây là việc nền, bận thì để lần sau dọn tiếp
    db = sqlite3.connect(db_path, timeout=10)
    try:
        db.execute("PRAGMA busy_timeout=10000")
        for table, days in (
            ("login_logs", LOGIN_RETENTION_DAYS),
            ("audit_logs", AUDIT_RETENTION_DAYS),
        ):
            cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            cur = db.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
            deleted[table] = cur.rowcount or 0
        db.commit()
    finally:
        db.close()

    if deleted["login_logs"] or deleted["audit_logs"]:
        _log.info(
            "Dọn nhật ký: xoá %d dòng login_logs, %d dòng audit_logs",
            deleted["login_logs"], deleted["audit_logs"],
        )
    return deleted


def _schedule_next(db_path: str):
    global _timer
    _timer = threading.Timer(
        _INTERVAL_HOURS * 3600,
        lambda: (_schedule_next(db_path), _run_safe(db_path)),
    )
    _timer.daemon = True
    _timer.start()


def _run_safe(db_path: str):
    """Lỗi dọn nhật ký không được làm chết luồng lịch."""
    try:
        run_cleanup(db_path)
    except Exception as exc:
        _log.error("Dọn nhật ký thất bại: %s", exc, exc_info=True)


def start_scheduler(db_path: str = "data/ksnb.db"):
    """Gọi khi khởi động app: dọn ngay (background) + lặp lại mỗi 12h."""
    threading.Thread(
        target=_run_safe, args=(db_path,), daemon=True, name="log-cleanup-init",
    ).start()
    _schedule_next(db_path)
    _log.info("Log cleanup scheduler khởi động — chu kỳ %dh", _INTERVAL_HOURS)
