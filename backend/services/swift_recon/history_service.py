# -*- coding: utf-8 -*-
"""
history_service.py
-------------------
Lưu & truy vấn lịch sử đối chiếu điện SWIFT — bảng `swift_recon_history`
trong ksnb.db (cùng 1 DB dùng chung của toàn hệ thống, KHÔNG lưu file/folder
riêng — theo đúng thống nhất với Người 1).

MỖI LẦN đối chiếu lưu ĐỦ 5 mảnh dữ liệu — TẤT CẢ đều là JSON (không phải
.xlsx, cho hệ thống đỡ nặng), đúng tinh thần: "miễn có dữ liệu, sau này muốn
xuất ra .xlsx cho auditor thì tính sau":

  - raw_a / raw_b      : dữ liệu THÔ đã parse từ 2 file người dùng import
                         (đầy đủ cột gốc) — chính là "file người dùng đã
                         upload", ở dạng dữ liệu chứ không phải byte gốc.
  - merged             : kết quả build_merged_view() (khớp + lệch) — dùng để
                         xem lại toàn bộ chi tiết.
  - summary            : kết quả summarize_counts() — chính là dữ liệu đứng
                         sau file Excel "Tổng hợp".
  - diff_a_only/diff_b_only/di_not_ack : dữ liệu đứng sau file Excel
                         "Chi tiết lệch".

QUAN TRỌNG cho audit: summary/diff được LƯU LẠI NGUYÊN VẸN tại thời điểm đối
chiếu, KHÔNG tính lại từ raw_a/raw_b mỗi lần xem — nếu sau này logic đối
chiếu (reconcile.py) có thay đổi, dữ liệu audit cũ vẫn đúng y hệt những gì
người dùng đã thấy/xuất ra tại thời điểm đó.

Raw SQL / sqlite3 thuần, không dùng ORM (đúng quy ước chung trong
CONTRIBUTING.md, mục "Tuyệt đối Không được Làm" #7).

Bảng này được tạo trong backend/db/migrations.py (_create_tables) — xem
SNIPPETS_TO_PASTE.md để biết đoạn CREATE TABLE cần thêm vào đó.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from backend.database import _vn_now


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def save_recon_history(
    db: sqlite3.Connection,
    recon_type: str,          # "den" hoặc "di"
    performed_by_id: Optional[int],
    file_saa_name: str,
    file_ql_name: str,
    total_saa: int,
    total_ql: int,
    total_matched: int,
    total_diff: int,
    merged_records: list,        # build_merged_view() -> list[dict]
    raw_a_records: list,         # DataFrame gốc bên A đã import -> list[dict]
    raw_b_records: list,         # DataFrame gốc bên B đã import -> list[dict]
    summary_records: list,       # summarize_counts() -> list[dict] (= data của Excel Tổng hợp)
    diff_a_only_records: list,   # diff_only_a() -> list[dict]
    diff_b_only_records: list,   # diff_only_b() -> list[dict]
    di_not_ack_records: Optional[list] = None,  # chỉ có ở điện đi
) -> int:
    """Lưu 1 lần đối chiếu — đầy đủ dữ liệu thô đã import + snapshot kết quả
    Tổng hợp/Chi tiết lệch ngay tại thời điểm này, phục vụ audit sau này."""
    cur = db.execute(
        """INSERT INTO swift_recon_history
           (recon_type, recon_date, performed_by_id, file_saa_name, file_ql_name,
            total_saa, total_ql, total_matched, total_diff,
            merged_json, raw_a_json, raw_b_json,
            summary_json, diff_a_only_json, diff_b_only_json, di_not_ack_json,
            created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            recon_type, _vn_now(), performed_by_id, file_saa_name, file_ql_name,
            total_saa, total_ql, total_matched, total_diff,
            _dumps(merged_records), _dumps(raw_a_records), _dumps(raw_b_records),
            _dumps(summary_records), _dumps(diff_a_only_records), _dumps(diff_b_only_records),
            _dumps(di_not_ack_records) if di_not_ack_records is not None else None,
            _vn_now(),
        ),
    )
    db.commit()
    return cur.lastrowid


def list_recon_history(db: sqlite3.Connection, limit: int = 100) -> list:
    """Danh sách lịch sử (không kèm dữ liệu JSON nặng — để nhẹ khi hiển thị bảng)."""
    rows = db.execute(
        """SELECT h.id, h.recon_type, h.recon_date, u.full_name AS performed_by,
                  h.file_saa_name, h.file_ql_name,
                  h.total_saa, h.total_ql, h.total_matched, h.total_diff
           FROM swift_recon_history h
           LEFT JOIN user_tttt u ON u.id = h.performed_by_id
           ORDER BY h.recon_date DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recon_detail(db: sqlite3.Connection, history_id: int) -> Optional[dict]:
    """Lấy lại đầy đủ 1 lần đối chiếu — merged view + 2 file gốc đã import +
    snapshot Tổng hợp/Chi tiết lệch (giải nén JSON)."""
    row = db.execute(
        "SELECT * FROM swift_recon_history WHERE id = ?", (history_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["merged_records"] = json.loads(d.pop("merged_json") or "[]")
    d["raw_a_records"] = json.loads(d.pop("raw_a_json") or "[]")
    d["raw_b_records"] = json.loads(d.pop("raw_b_json") or "[]")
    d["summary_records"] = json.loads(d.pop("summary_json") or "[]")
    d["diff_a_only_records"] = json.loads(d.pop("diff_a_only_json") or "[]")
    d["diff_b_only_records"] = json.loads(d.pop("diff_b_only_json") or "[]")
    raw_not_ack = d.pop("di_not_ack_json")
    d["di_not_ack_records"] = json.loads(raw_not_ack) if raw_not_ack else None
    return d
