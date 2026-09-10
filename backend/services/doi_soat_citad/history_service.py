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
import logging
import sqlite3
from datetime import datetime
from typing import Optional

from backend.database import _vn_now

_log = logging.getLogger(__name__)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ── Cảnh báo lượt đối soát bất thường ────────────────────────────────────────
# Một lượt bình thường lệch vài chục lệnh. Đo trên dữ liệu thật: 6, 14, 15, 39 —
# rồi đột ngột 22 202, 60 542, 75 921, 93 781. Những lượt sau gần như chắc chắn
# là ghép NHẦM CẶP FILE (file CITAD của ngày này với IPCAS của ngày khác chẳng
# hạn): không khớp được gì nên mọi giao dịch đều bị coi là lệch.
#
# Hai điều kiện phải cùng đúng, cố ý:
#   - tỷ lệ cao: quá nửa số giao dịch bị coi là lệch — đối soát mà hỏng quá nửa
#     thì không còn là "có sai sót", mà là hai file không cùng một gốc;
#   - số tuyệt đối lớn: ngày ít giao dịch (3 lệnh, lệch 2) vẫn quá nửa nhưng
#     hoàn toàn bình thường — không có ngưỡng này thì cảnh báo kêu suốt và
#     người dùng học cách bỏ qua nó.
_TY_LE_LECH_BAT_THUONG = 0.5
_SO_LECH_BAT_THUONG = 1000


def canh_bao_lech_bat_thuong(n_lech: int, total_citad: int,
                             total_ipcas: int, total_hub: int) -> Optional[str]:
    """Câu cảnh báo nếu lượt đối soát có dấu hiệu ghép nhầm file, None nếu bình thường."""
    lon_nhat = max(total_citad, total_ipcas, total_hub)
    if n_lech < _SO_LECH_BAT_THUONG or lon_nhat <= 0:
        return None
    ty_le = n_lech / lon_nhat
    if ty_le < _TY_LE_LECH_BAT_THUONG:
        return None
    return (
        f"Có {n_lech:,} lệnh lệch trên tổng {lon_nhat:,} — tức {ty_le:.0%}. "
        "Tỷ lệ này thường có nghĩa các file nguồn KHÔNG cùng một ngày hoặc "
        "không cùng một hệ thống, chứ không phải nghiệp vụ sai. Kiểm tra lại "
        "cặp file đã chọn trước khi dùng kết quả này."
    )


def _parse_ngay(ngay: str) -> Optional[datetime]:
    """`ngay_cham` lưu dạng text dd/mm/yyyy — không so sánh chuỗi trực tiếp
    (sai thứ tự thời gian, ví dụ "01/12/2026" < "05/01/2026" theo string
    nhưng đến sau). Trả None nếu không parse được (bỏ qua dòng đó khi lọc,
    không để sập cả danh sách)."""
    try:
        return datetime.strptime(ngay.strip(), "%d/%m/%Y")
    except Exception:
        return None


# ── Bảng con `doi_soat_citad_lech` ───────────────────────────────────────────
# Các khoá có cột riêng. Khoá nào KHÔNG nằm đây rơi vào `extra_json` — bản ghi
# lệch dựng bằng `{**r, ...}` nên bộ khoá theo dòng nguồn, không cố định.
_COT_LECH = (
    "so_gd", "dich_vu", "loai", "chieu", "loai_tien", "so_tien",
    "ngay", "status", "key_agri", "nh_nhan", "trang_thai", "cong", "ghi_chu",
)


def _tach_ban_ghi(rec: dict) -> tuple:
    """Bản ghi lệch → tuple giá trị theo `_COT_LECH`, phần dư gói vào extra_json."""
    du = {k: v for k, v in rec.items() if k not in _COT_LECH}
    return tuple(rec.get(k) for k in _COT_LECH) + (_dumps(du) if du else None,)


def _ghep_ban_ghi(row: sqlite3.Row) -> dict:
    """Dòng DB → bản ghi lệch y như lúc lưu.

    Chỉ trả về khoá THỰC SỰ có lúc lưu: cột NULL nghĩa là bản ghi gốc không có
    khoá đó (`cong`/`ghi_chu` vắng ở nhiều dòng), trả kèm `None` là bịa thêm
    field mà bản gốc không có — Excel xuất ra sẽ khác bản đã ký.
    """
    rec = {k: row[k] for k in _COT_LECH if row[k] is not None}
    if row["extra_json"]:
        rec.update(json.loads(row["extra_json"]))
    return rec


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
            None, _vn_now(),
        ),
    )
    history_id = cur.lastrowid

    # executemany một phát: 93 781 lệnh lệch mà chạy execute() từng dòng thì
    # riêng vòng lặp Python đã lâu hơn cả lượt đối soát.
    db.executemany(
        f"""INSERT INTO doi_soat_citad_lech
            (history_id, seq, {", ".join(_COT_LECH)}, extra_json)
            VALUES ({", ".join("?" * (len(_COT_LECH) + 3))})""",
        [(history_id, i) + _tach_ban_ghi(rec) for i, rec in enumerate(lech_rows)],
    )
    db.commit()
    return history_id


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


# Mọi cột của bảng cha TRỪ `lech_json`. Liệt kê tên thay cho `SELECT *`: cột đó
# còn tồn tại cho tới khi dữ liệu cũ được chuyển hết, và `SELECT *` sẽ kéo trọn
# 19 MB lên RAM ngay cả khi không ai dùng tới nó.
_COT_CHA = """h.id, h.ngay_cham, h.recon_date, h.performed_by_id,
              h.citad_file_names, h.ipcas_file_names, h.hub_file_names,
              h.total_citad, h.total_ipcas, h.total_hub, h.n_khop, h.n_lech,
              h.created_at"""


def get_recon_detail(
    db: sqlite3.Connection,
    history_id: int,
    offset: int = 0,
    limit: Optional[int] = 200,
) -> Optional[dict]:
    """Một lần đối soát + MỘT TRANG lệnh lệch.

    `limit=None` lấy hết — chỉ dùng cho đường xuất Excel, không dùng cho màn
    hình: một lượt đối soát hỏng có tới 93 781 lệnh, trả hết là 97 MB RAM.
    """
    row = db.execute(
        f"SELECT {_COT_CHA} FROM doi_soat_citad_history h WHERE h.id = ?", (history_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["citad_file_names"] = json.loads(d.pop("citad_file_names") or "[]")
    d["ipcas_file_names"] = json.loads(d.pop("ipcas_file_names") or "[]")
    d["hub_file_names"] = json.loads(d.pop("hub_file_names") or "[]")

    # Tổng số lệnh lệch THẬT trong bảng con, không lấy `n_lech` của bảng cha:
    # hai số này lệch nhau nếu một lượt lưu hụt giữa chừng, và phân trang phải
    # bám theo thứ có thật thì mới không hiện trang trống ở cuối.
    tong = db.execute(
        "SELECT COUNT(*) FROM doi_soat_citad_lech WHERE history_id = ?", (history_id,)
    ).fetchone()[0]

    if tong:
        sql = "SELECT * FROM doi_soat_citad_lech WHERE history_id = ? ORDER BY seq"
        tham_so: list = [history_id]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            tham_so += [limit, offset]
        d["lech_records"] = [_ghep_ban_ghi(r) for r in db.execute(sql, tham_so)]
    else:
        d["lech_records"], tong = _doc_ban_cu(db, history_id, offset, limit)

    d["lech_offset"] = offset
    d["lech_total"] = tong
    return d


def _doc_ban_cu(db: sqlite3.Connection, history_id: int,
                offset: int, limit: Optional[int]) -> tuple[list, int]:
    """Đường lui: đọc lệnh lệch từ cột `lech_json` cũ khi bảng con chưa có dữ liệu.

    Cần vì mã và dữ liệu chuyển sang bảng con ở HAI bước rời nhau: deploy mã
    trước, chạy `scripts/chuyen_lech_json_sang_bang_con.py` sau. Không có đường
    lui này thì trong khoảng giữa, mọi lượt lịch sử cũ hiện ra **0 lệnh lệch** —
    không lỗi, không log, người dùng tưởng mất sạch dữ liệu audit. Phát hiện lúc
    chạy thử trên máy thật, không phải suy đoán.

    Chậm (phải giải nén cả chuỗi JSON, dòng nặng nhất 19 MB / ~1 giây) nên KÊU TO
    mỗi lần dùng: đây là trạng thái tạm, phải chạy script chuyển cho xong.
    """
    row = db.execute(
        "SELECT lech_json FROM doi_soat_citad_history WHERE id = ?", (history_id,)
    ).fetchone()
    raw = row["lech_json"] if row else None
    if not raw:
        return [], 0
    _log.warning(
        "Lượt đối soát id=%s còn nằm ở cột lech_json cũ — đang đọc đường chậm. "
        "Chạy scripts/chuyen_lech_json_sang_bang_con.py để chuyển dứt điểm.",
        history_id,
    )
    ban_ghi = json.loads(raw)
    tong = len(ban_ghi)
    if limit is None:
        return ban_ghi, tong
    return ban_ghi[offset:offset + limit], tong


def iter_lech(db: sqlite3.Connection, history_id: int, lo: int = 2000):
    """Duyệt toàn bộ lệnh lệch theo lô — cho đường xuất Excel.

    Sinh từng bản ghi thay vì trả cả danh sách: openpyxl vốn đã giữ cả bảng
    tính trong RAM, không cần cõng thêm một bản sao của dữ liệu nguồn.
    """
    offset = 0
    while True:
        rows = db.execute(
            "SELECT * FROM doi_soat_citad_lech WHERE history_id = ? "
            "ORDER BY seq LIMIT ? OFFSET ?",
            (history_id, lo, offset),
        ).fetchall()
        if not rows:
            return
        for r in rows:
            yield _ghep_ban_ghi(r)
        offset += lo
