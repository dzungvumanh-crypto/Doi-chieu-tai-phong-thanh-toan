# -*- coding: utf-8 -*-
"""
history_service.py
-------------------
Lưu & truy vấn lịch sử đối soát CITAD ↔ IPCAS — bảng `doi_soat_citad_history`
trong ksnb.db (DB dùng chung của hệ thống).

TÍNH NĂNG MỚI so với bản gốc `citad-fixed/DoiSoatCITAD.py` (bản gốc KHÔNG có
DB/lịch sử — mỗi lần đối soát chỉ hiện kết quả trên màn hình rồi xuất Excel,
`init_db/clear_session/insert_*` trong file gốc đều là stub rỗng). Thêm bảng
này để khớp chuẩn trải nghiệm với các module đối chiếu khác (xem
`backend/services/swift_recon/history_service.py` — cùng khuôn mẫu).

Raw SQL / sqlite3 thuần, không dùng ORM (theo quy ước chung của dự án —
CONTRIBUTING.md, mục "Tuyệt đối Không được Làm").
Bảng đã tạo sẵn trong backend/db/migrations.py (cùng PR này).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from backend.database import _vn_now


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _parse_ngay(ngay: str) -> Optional[datetime]:
    """`ngay_cham` lưu dạng text dd/mm/yyyy — không so sánh chuỗi trực tiếp
    (sai thứ tự thời gian, ví dụ "01/12/2026" < "05/01/2026" theo string
    nhưng đến sau). Trả None nếu không parse được (bỏ qua dòng đó khi lọc,
    không để sập cả danh sách)."""
    try:
        return datetime.strptime(ngay.strip(), "%d/%m/%Y")
    except Exception:
        return None


def save_recon_history(
    db: sqlite3.Connection,
    ngay_cham: str,
    performed_by_id: Optional[int],
    citad_file_names: list,
    ipcas_file_names: list,
    hub_file_names: list,
    total_citad: int,
    total_ipcas: int,
    total_hub: int,
    n_khop: int,
    lech_rows: list,
) -> int:
    """Lưu 1 lần đối soát — snapshot đầy đủ `lech` (danh sách lệnh lệch) tại
    thời điểm chạy, phục vụ audit sau này (đúng tinh thần swift_recon:
    không tính lại từ file gốc khi xem lại lịch sử)."""
    n_lech = len(lech_rows)
    cur = db.execute(
        """INSERT INTO doi_soat_citad_history
           (ngay_cham, recon_date, performed_by_id,
            citad_file_names, ipcas_file_names, hub_file_names,
            total_citad, total_ipcas, total_hub, n_khop, n_lech,
            lech_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ngay_cham, _vn_now(), performed_by_id,
            _dumps(citad_file_names), _dumps(ipcas_file_names), _dumps(hub_file_names),
            total_citad, total_ipcas, total_hub, n_khop, n_lech,
            _dumps(lech_rows), _vn_now(),
        ),
    )
    db.commit()
    return cur.lastrowid


def list_recon_history(
    db: sqlite3.Connection,
    limit: int = 100,
    tu_ngay: Optional[str] = None,
    den_ngay: Optional[str] = None,
    nguoi_thuc_hien: Optional[str] = None,
) -> list:
    """Danh sách lịch sử (không kèm `lech_json` nặng — để nhẹ khi hiển thị
    bảng), lọc theo khoảng "ngày chấm" (`ngay_cham`, dd/mm/yyyy — parse
    bằng Python cùng lý do với get_reconciliation_days() bên
    doi_chieu_citad_service.py) và tên người thực hiện (khớp gần đúng,
    không phân biệt hoa/thường).

    Không lọc gì (trường hợp phổ biến nhất — chỉ xem lịch sử gần đây):
    giới hạn ngay ở SQL bằng LIMIT, khỏi tải cả bảng. Có lọc ngày/tên:
    BẮT BUỘC tải hết rồi lọc bằng Python (không lọc `ngay_cham` bằng SQL
    được vì lưu dạng text dd/mm/yyyy, so chuỗi sai thứ tự thời gian) —
    `limit` áp dụng SAU khi lọc trong trường hợp này."""
    no_filter = not (tu_ngay or den_ngay or nguoi_thuc_hien)
    base_sql = """SELECT h.id, h.ngay_cham, h.recon_date, u.full_name AS performed_by,
                  h.citad_file_names, h.ipcas_file_names, h.hub_file_names,
                  h.total_citad, h.total_ipcas, h.total_hub, h.n_khop, h.n_lech
           FROM doi_soat_citad_history h
           LEFT JOIN user_tttt u ON u.id = h.performed_by_id
           ORDER BY h.recon_date DESC"""
    if no_filter:
        rows = db.execute(base_sql + " LIMIT ?", (limit,)).fetchall()
    else:
        rows = db.execute(base_sql).fetchall()

    tu_dt = _parse_ngay(tu_ngay) if tu_ngay else None
    den_dt = _parse_ngay(den_ngay) if den_ngay else None
    nguoi_kw = nguoi_thuc_hien.strip().lower() if nguoi_thuc_hien else None

    out = []
    for r in rows:
        if tu_dt or den_dt:
            d = _parse_ngay(r["ngay_cham"])
            if d is None:  # bỏ qua dòng ngày lỗi định dạng khi có lọc ngày
                continue
            if tu_dt and d < tu_dt:
                continue
            if den_dt and d > den_dt:
                continue
        if nguoi_kw and nguoi_kw not in (r["performed_by"] or "").lower():
            continue
        d = dict(r)
        d["citad_file_names"] = json.loads(d.pop("citad_file_names") or "[]")
        d["ipcas_file_names"] = json.loads(d.pop("ipcas_file_names") or "[]")
        d["hub_file_names"] = json.loads(d.pop("hub_file_names") or "[]")
        out.append(d)
        if len(out) >= limit:
            break
    return out


def get_recon_detail(db: sqlite3.Connection, history_id: int) -> Optional[dict]:
    """Lấy lại đầy đủ 1 lần đối soát — snapshot `lech` (giải nén JSON)."""
    row = db.execute(
        "SELECT * FROM doi_soat_citad_history WHERE id = ?", (history_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["citad_file_names"] = json.loads(d.pop("citad_file_names") or "[]")
    d["ipcas_file_names"] = json.loads(d.pop("ipcas_file_names") or "[]")
    d["hub_file_names"] = json.loads(d.pop("hub_file_names") or "[]")
    d["lech_records"] = json.loads(d.pop("lech_json") or "[]")
    return d
