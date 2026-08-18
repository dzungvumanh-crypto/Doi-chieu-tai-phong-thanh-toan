"""Backup tự động — giữ một bản mỗi ngày trong 7 ngày, cộng vài bản gần nhất.

Tiêu chí xoá cũ (đổi 18/08/2026) dựa trên ba điều đã đo được ở thư mục thật:

1. **Chỉ xoá file DO CHÍNH SCHEDULER SINH RA.** Luật cũ glob `ksnb_*.db` nên vơ
   luôn cả bản người ta đặt tay trước khi làm việc nguy hiểm
   (`ksnb_before_cleanup_537_20260720_134609.db`, `ksnb_truoc_nhomA_20260728.db`).

2. **Sắp theo MỐC THỜI GIAN đọc từ tên, không sắp theo tên.** Luật cũ dùng
   `sorted()` trên đường dẫn: `'2' < 'b' < 't'`, nên hai bản đặt tay ở trên luôn
   nằm CUỐI danh sách và bị coi là "mới nhất". Hậu quả kép:
     - chúng vĩnh viễn chiếm 2 trong 7 chỗ, còn bản theo ngày thật bị xoá trước;
     - `last_backup_info()` lấy `backups[-1]` nên màn hình Admin báo
       "Backup gần nhất: 28/07/2026" trong khi vừa có bản của hôm nay.

3. **Khởi động lại nhiều lần trong ngày không được cuốn trôi lịch sử.**
   `start_scheduler()` backup NGAY mỗi lần app khởi động, mà `run.py` tự khởi
   động lại tới 5 lần khi gặp sự cố. Với luật "giữ 7 file mới nhất" (thực chất
   còn 5 vì 2 chỗ bị chiếm), một vòng khởi động lại là **cả tuần lịch sử biến
   mất**, thay bằng 5 bản chụp cách nhau vài giây. Cơ sở dữ liệu này đã từng
   hỏng thật (xem 3 file `ksnb_corrupt*.db` trong `data/`) — hỏng thường phát
   hiện muộn, nên chiều sâu lịch sử mới là thứ cứu được, không phải số lượng
   file.

Nên tiêu chí mới là hợp của hai tập, giữ cả hai:
  * bản **mới nhất của mỗi ngày**, cho `_GIU_NGAY` ngày gần nhất → chiều sâu;
  * `_GIU_GAN_NHAT` bản mới nhất bất kể ngày → chống mất bản chụp vừa tạo khi
    một ngày có nhiều lần backup.
"""
import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from backend.core.config import BASE_DIR

_log = logging.getLogger(__name__)
_BACKUP_DIR = BASE_DIR / "data" / "backups"

# Giữ bản mới nhất của mỗi ngày, trong ngần này ngày gần nhất.
_GIU_NGAY = 7
# Giữ thêm ngần này bản mới nhất bất kể ngày (một ngày khởi động lại nhiều lần).
_GIU_GAN_NHAT = 5

_INTERVAL_HOURS = 24

# Đúng mẫu tên do run_backup() sinh: ksnb_YYYYMMDD_HHMM.db — và CHỈ mẫu này mới
# bị xoá tự động. File tên khác trong cùng thư mục là do người đặt, không đụng.
_TEN_TU_SINH = re.compile(r"^ksnb_(\d{8})_(\d{4})\.db$")

# Ref timer toàn cục để có thể hủy khi test
_timer: threading.Timer | None = None


def _ban_tu_sinh(backup_dir: Path) -> list[tuple[str, str, Path]]:
    """[(mốc_thời_gian, ngày, path)] các bản do scheduler tạo — sắp CŨ → MỚI.

    Mốc đọc từ tên file chứ không từ `mtime`: chép thư mục backup sang ổ khác
    (`BACKUP_EXTRA_DIR` dùng `shutil.copy2`, hoặc người ta tự chép tay) có thể
    làm mtime đổi hết, còn tên thì không.
    """
    ra = []
    for p in backup_dir.glob("ksnb_*.db"):
        m = _TEN_TU_SINH.match(p.name)
        if m:
            ra.append((m.group(1) + m.group(2), m.group(1), p))
    ra.sort(key=lambda t: t[0])
    return ra


def _rotate(backup_dir: Path):
    """Xoá bản tự sinh đã quá hạn giữ. Không bao giờ đụng file người đặt tay."""
    ban = _ban_tu_sinh(backup_dir)
    if not ban:
        return

    giu = {p for _, _, p in ban[-_GIU_GAN_NHAT:]}

    # Duyệt cũ → mới nên giá trị đọng lại của mỗi ngày là bản mới nhất ngày đó.
    moi_nhat_theo_ngay: dict[str, Path] = {}
    for _, ngay, p in ban:
        moi_nhat_theo_ngay[ngay] = p
    for ngay in sorted(moi_nhat_theo_ngay)[-_GIU_NGAY:]:
        giu.add(moi_nhat_theo_ngay[ngay])

    for _, _, p in ban:
        if p in giu:
            continue
        try:
            p.unlink()
            _log.info("Dọn backup quá hạn: %s", p.name)
        except OSError as exc:
            # Trước đây nuốt im lặng. File bị khoá (đang mở bằng công cụ xem DB)
            # thì thư mục cứ phình mà không ai biết vì sao.
            _log.warning("Không xoá được backup cũ %s: %s", p.name, exc)


def _verify(db_file: Path) -> bool:
    """Kiểm tra bản backup vừa tạo có toàn vẹn không (chống đẻ ra bản hỏng)."""
    try:
        c = sqlite3.connect(str(db_file))
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.close()
        return ok
    except Exception:
        return False


def _mirror(dst: Path):
    """Sao chép bản backup sang thư mục phụ (ổ/máy khác) nếu được cấu hình."""
    from backend.core.config import settings
    extra = settings.BACKUP_EXTRA_DIR
    if not extra:
        return
    try:
        extra_dir = Path(extra)
        extra_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, extra_dir / dst.name)
        _rotate(extra_dir)
        _log.info("Backup phụ hoàn tất → %s", extra_dir / dst.name)
    except Exception as exc:
        # Thư mục phụ lỗi không được làm hỏng backup chính
        _log.error("Backup phụ thất bại (%s): %s", extra, exc)


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

        # Chống rủi ro backup ra bản hỏng — cảnh báo nhưng vẫn giữ file để điều tra
        if not _verify(dst):
            _log.error("Backup vừa tạo KHÔNG toàn vẹn: %s (file chính có thể đã hỏng)", dst)

        _rotate(_BACKUP_DIR)
        _mirror(dst)
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
    """Gọi khi khởi động app: backup ngay (background) + lên lịch mỗi 24h."""
    def _initial():
        try:
            run_backup(db_path)
        except Exception:
            pass

    # Chạy backup đầu tiên trong background để không block lifespan của FastAPI
    threading.Thread(target=_initial, daemon=True, name="backup-init").start()
    _schedule_next(db_path)
    _log.info("Backup scheduler khởi động — chu kỳ %dh, giữ 1 bản/ngày trong %d ngày "
              "+ %d bản gần nhất", _INTERVAL_HOURS, _GIU_NGAY, _GIU_GAN_NHAT)


def last_backup_info() -> dict:
    """Thông tin bản backup TỰ ĐỘNG gần nhất, để hiển thị ở màn hình Admin.

    Lấy theo mốc thời gian trong tên, không phải `sorted()[-1]` như trước —
    bản đặt tay (`ksnb_truoc_nhomA_...`) sắp sau bản theo ngày về mặt chữ cái
    nên luôn thắng, khiến màn hình báo ngày backup gần nhất SỚM HƠN sự thật
    hàng tuần. Người vận hành nhìn vào đó để biết backup còn chạy hay không,
    báo sai ở đây là nguy hiểm hơn không hiển thị gì.
    """
    if not _BACKUP_DIR.exists():
        return {"exists": False, "path": None, "time": None}
    ban = _ban_tu_sinh(_BACKUP_DIR)
    so_thu_cong = len(list(_BACKUP_DIR.glob("ksnb_*.db"))) - len(ban)
    if not ban:
        return {"exists": False, "path": None, "time": None,
                "count_thu_cong": so_thu_cong}
    khoa, _, last = ban[-1]
    return {
        "exists": True,
        "path": str(last),
        "time": datetime.strptime(khoa, "%Y%m%d%H%M").strftime("%H:%M %d/%m/%Y"),
        "count": len(ban),
        "count_thu_cong": so_thu_cong,
    }
