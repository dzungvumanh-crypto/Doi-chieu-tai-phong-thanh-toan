"""Thư mục nhận file tải lên của Đối soát CITAD — `data/temp_citad/<lượt>/`.

Trước đây file đi vào thư mục tạm của Windows (`tempfile.NamedTemporaryFile`).
Đổi về trong dự án vì hai lẽ:

  * người vận hành tra được file của một lượt đối soát khi cần đối chiếu lại —
    `%TEMP%` là hộp đen, tên file ngẫu nhiên, không biết của lượt nào;
  * cùng một chỗ với ACH / 459901 / song phương thì cùng một lịch dọn 23h
    (`backend/services/temp_cleanup_service.py`) trông coi, không còn góc nào
    dọn theo luật riêng.

Khác ba tính năng kia ở một điểm: file ở đây chỉ dùng trong đúng một request —
parse xong là `xoa()` ngay trong `finally`. Lịch 23h chỉ là lưới hứng cho những
lượt chết giữa chừng (client cắt kết nối, backend bị tắt), nên thư mục này
thường xuyên rỗng — đúng như vậy mới là bình thường.
"""
import logging
import shutil
import uuid
from pathlib import Path

from backend.core.config import BASE_DIR
from backend.core.don_dep import moc_don_gan_nhat

_log = logging.getLogger(__name__)

TEMP_DIR = BASE_DIR / "data" / "temp_citad"


def tao_thu_muc_luot() -> Path:
    """Thư mục riêng cho một lượt đối soát."""
    d = TEMP_DIR / uuid.uuid4().hex[:12]
    d.mkdir(parents=True, exist_ok=True)
    return d


def xoa(thu_muc: Path) -> None:
    shutil.rmtree(thu_muc, ignore_errors=True)


def _cleanup_old_results(cutoff: float | None = None) -> None:
    """Xoá thư mục lượt cũ hơn `cutoff` (mặc định: mốc 23h gần nhất đã qua)."""
    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff
    if not TEMP_DIR.exists():
        return
    for d in TEMP_DIR.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError as e:
            _log.warning("Không xoá được thư mục CITAD %s: %s", d, e)
