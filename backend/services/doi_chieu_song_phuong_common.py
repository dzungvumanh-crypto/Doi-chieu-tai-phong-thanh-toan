"""Helper dùng chung cho mọi pipeline Đối chiếu Song phương cần dò file theo NGÀY trong 1 thư
mục gốc chứa thư mục con theo ngày (`D.M` hoặc `D.M.YYYY`) và/hoặc file rời ở thư mục gốc.

Tách ra từ `doi_chieu_song_phuong_core/pipeline.py` (2026-08-28) khi thêm service điều phối
`doi_chieu_song_phuong_kenh_core_service.py` — cả 2 nơi cần cùng logic dò thư mục ngày, tránh
reach vào hàm `_private` của gói khác.
"""

from datetime import datetime, timedelta
from pathlib import Path


def thu_muc_ngay_ung_vien(goc_dir: Path, ngay: str) -> list[Path]:
    """`ngay` dạng YYYYMMDD -> danh sách thư mục con khả dĩ, dạng `D.M` (VD `23.8`) — đúng quy
    ước dữ liệu 21-25/08. Dữ liệu bộ NH 201/311 (thư mục `TRANG/`) lại đặt tên `D.M.YYYY` (VD
    `24.8.2026`) — thử tên chuẩn trước, rồi glob mọi thư mục con bắt đầu đúng `D.M` để không phải
    thêm 1 hàm biến thể mỗi lần nguồn đổi cách đặt tên (giống cách đã làm cho tên file kênh)."""
    d = datetime.strptime(ngay, "%Y%m%d")
    prefix = f"{d.day}.{d.month}"
    ung_vien = [goc_dir / prefix]
    if goc_dir.exists():
        for sub in sorted(goc_dir.iterdir()):
            if sub.is_dir() and sub.name.startswith(prefix) and sub not in ung_vien:
                ung_vien.append(sub)
    return ung_vien


def cong_ngay(ngay: str, so_ngay: int) -> str:
    d = datetime.strptime(ngay, "%Y%m%d") + timedelta(days=so_ngay)
    return d.strftime("%Y%m%d")


def nhan_offset(off: int) -> str:
    return "T" if off == 0 else f"T{off:+d}"


def tim_file(goc_dir: Path, ngay: str, ten_file: str) -> Path | None:
    """Thử các thư mục ngày khả dĩ trước, rồi thư mục cha (file để rời không có thư mục riêng)."""
    for d in (*thu_muc_ngay_ung_vien(goc_dir, ngay), goc_dir):
        p = d / ten_file
        if p.exists():
            return p
    return None


def tim_file_glob(goc_dir: Path, ngay: str, pattern: str) -> list[Path]:
    """Như `tim_file`, nhưng khớp `pattern` kiểu glob (VD `202_DEN*.csv`) thay vì tên chính xác —
    dữ liệu thật xuất thủ công thường kèm hậu tố ngày/giờ xuất (VD `202_DEN_20260827_1408.csv`),
    không đúng tên chuẩn module Phân loại dữ liệu xuất ra (`202_DEN.csv`). Dừng ở thư mục ĐẦU
    TIÊN có ít nhất 1 khớp (không gộp khớp từ nhiều thư mục ngày khác nhau); trả rỗng nếu không
    thấy đâu cả."""
    for d in (*thu_muc_ngay_ung_vien(goc_dir, ngay), goc_dir):
        if not d.exists():
            continue
        matches = sorted(d.glob(pattern))
        if matches:
            return matches
    return []
