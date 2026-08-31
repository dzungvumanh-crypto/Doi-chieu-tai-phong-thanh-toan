"""Đọc / ghi cấu hình quy chuẩn trong DB (bảng `vb_format_config`, đúng 1 dòng).

## Vì sao lưu nguyên khối JSON chứ không tách thành cột

Cấu hình là 28 thành phần thể thức × 7 thuộc tính, cộng bốn nhóm tuỳ chọn và
hai danh sách cụm từ. Tách thành cột thì mỗi lần bổ sung một thuộc tính trình
bày là một migration mới; tách thành bảng khoá–giá trị thì mọi lần đọc phải
dựng lại cây từ mấy trăm dòng. Không có ai truy vấn theo từng thuộc tính, cũng
không có báo cáo nào thống kê trên nó — đây là dữ liệu chỉ đọc trọn gói.

## Chỉ lưu phần KHÁC mặc định

`ghi_cau_hinh()` lọc bỏ mọi giá trị trùng với `quy_chuan.mac_dinh()`. Nhờ vậy
khi quy định đổi (hoặc khi sửa mặc định trong mã nguồn), những mục người dùng
chưa từng đụng tới sẽ tự đi theo mặc định mới. Lưu trọn bản sao thì cấu hình
đông cứng ở phiên bản lúc bấm Lưu, và không ai nhận ra cho tới khi in ra thấy
sai — vì màn hình vẫn hiện đúng cái đã lưu.
"""
import json
import logging
import sqlite3

from backend.database import _vn_now

from . import quy_chuan

_log = logging.getLogger(__name__)


def _khac_mac_dinh(nguoi_dung: dict, goc: dict) -> dict:
    """Giữ lại đúng những khoá có giá trị khác `goc`, đệ quy một cấp con."""
    ket_qua: dict = {}
    for khoa, gia_tri in (nguoi_dung or {}).items():
        if khoa not in goc:
            continue
        if isinstance(gia_tri, dict) and isinstance(goc[khoa], dict):
            con = _khac_mac_dinh(gia_tri, goc[khoa])
            if con:
                ket_qua[khoa] = con
        elif gia_tri != goc[khoa]:
            ket_qua[khoa] = gia_tri
    return ket_qua


def doc_cau_hinh(db: sqlite3.Connection) -> dict:
    """Phần cấu hình người dùng đã đổi (chưa hợp nhất với mặc định)."""
    row = db.execute("SELECT config_json FROM vb_format_config WHERE id = 1").fetchone()
    if not row or not row["config_json"]:
        return {}
    try:
        return json.loads(row["config_json"])
    except (ValueError, TypeError) as e:
        # Không để một dòng JSON hỏng chặn cả tính năng: quay về mặc định và
        # ghi log để người quản trị biết mà đặt lại. Chuẩn hoá theo quy định
        # gốc vẫn đúng, chỉ là mất phần đơn vị tự chỉnh.
        _log.error("vb_format_config hỏng, dùng quy chuẩn mặc định: %s", e)
        return {}


def doc_day_du(db: sqlite3.Connection) -> dict:
    """Cấu hình đã hợp nhất — thứ đem đi chuẩn hoá văn bản."""
    return quy_chuan.hop_nhat(doc_cau_hinh(db))


def ghi_cau_hinh(db: sqlite3.Connection, cau_hinh: dict, staff_id: int | None) -> dict:
    """Lưu cấu hình (chỉ phần khác mặc định). Trả bản đã hợp nhất."""
    rut_gon = _khac_mac_dinh(cau_hinh or {}, quy_chuan.mac_dinh())
    db.execute(
        """INSERT INTO vb_format_config (id, config_json, updated_at, updated_by)
           VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               config_json = excluded.config_json,
               updated_at  = excluded.updated_at,
               updated_by  = excluded.updated_by""",
        (json.dumps(rut_gon, ensure_ascii=False), _vn_now(), staff_id),
    )
    db.commit()
    return quy_chuan.hop_nhat(rut_gon)


def dat_lai_mac_dinh(db: sqlite3.Connection, staff_id: int | None) -> dict:
    db.execute(
        """INSERT INTO vb_format_config (id, config_json, updated_at, updated_by)
           VALUES (1, '{}', ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               config_json = '{}', updated_at = excluded.updated_at,
               updated_by = excluded.updated_by""",
        (_vn_now(), staff_id),
    )
    db.commit()
    return quy_chuan.mac_dinh()
