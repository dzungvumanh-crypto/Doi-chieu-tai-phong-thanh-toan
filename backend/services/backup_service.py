"""Backup tự động hàng ngày — lưu tối đa 7 bản gần nhất."""
import logging
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_log = logging.getLogger(__name__)
_BACKUP_DIR = Path("data/backups")
_KEEP = 7
_INTERVAL_HOURS = 24

# Ref timer toàn cục để có thể hủy khi test
_timer: threading.Timer | None = None


def _rotate(backup_dir: Path):
    """Xóa bản cũ, chỉ giữ _KEEP bản mới nhất."""
    backups = sorted(backup_dir.glob("ksnb_*.db"))
    for old in backups[:-_KEEP]:
        try:
            old.unlink()
        except Exception:
            pass


def run_backup(db_path: str = "data/ksnb.db") -> Path:
    """Tạo một bản sao an toàn bằng SQLite online backup API."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    dst = _BACKUP_DIR / f"ksnb_{stamp}.db"
    try:
        src = sqlite3.connect(db_path)
        bak = sqlite3.connect(str(dst))
        src.backup(bak)
        bak.close()
        src.close()
        _rotate(_BACKUP_DIR)
        _log.info("Backup hoàn tất → %s", dst)
        return dst
    except Exception as exc:
        _log.error("Backup thất bại: %s", exc)
        raise


def _schedule_next(db_path: str):
    """Lên lịch backup kế tiếp sau 24 giờ."""
    global _timer
    _timer = threading.Timer(
        _INTERVAL_HOURS * 3600,
        lambda: (_schedule_next(db_path), run_backup(db_path)),
    )
    _timer.daemon = True
    _timer.start()


def start_scheduler(db_path: str = "data/ksnb.db"):
    """Gọi khi khởi động app: backup ngay + lên lịch mỗi 24h."""
    try:
        run_backup(db_path)
    except Exception:
        pass  # Lỗi backup lúc khởi động không nên làm app crash
    _schedule_next(db_path)
    _log.info("Backup scheduler khởi động — chu kỳ %dh, lưu tối đa %d bản", _INTERVAL_HOURS, _KEEP)


def last_backup_info() -> dict:
    """Trả thông tin bản backup gần nhất để hiển thị ở Admin."""
    backups = sorted(_BACKUP_DIR.glob("ksnb_*.db")) if _BACKUP_DIR.exists() else []
    if not backups:
        return {"exists": False, "path": None, "time": None}
    last = backups[-1]
    mtime = datetime.fromtimestamp(last.stat().st_mtime)
    return {
        "exists": True,
        "path": str(last),
        "time": mtime.strftime("%H:%M %d/%m/%Y"),
        "count": len(backups),
    }
