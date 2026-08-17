"""
Duty Staff Service — quản lý nhân sự phân lịch trực Phòng Thanh toán.
Tái sử dụng user_tttt; duty_staff_meta chỉ lưu cài đặt phân lịch.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

_VN_TZ = timezone(timedelta(hours=7))

# ── SQL gốc để lấy staff Phòng Thanh toán ─────────────────────────────────────
_STAFF_SQL = """
SELECT u.id, u.full_name, u.role,
       CASE WHEN u.role IN ('truong_phong','pho_phong') THEN 'LD' ELSE 'NV' END AS duty_role,
       COALESCE(m.can_do_sp, 0)    AS can_do_sp,
       COALESCE(m.is_on_project, 0) AS is_on_project,
       COALESCE(m.display_order, 999) AS display_order
FROM user_tttt u
JOIN departments d ON u.department_id = d.id
LEFT JOIN duty_staff_meta m ON u.id = m.user_id
WHERE u.is_active = 1 AND u.is_deleted = 0 AND d.code = 'PAYMENT'
  AND u.role IN ('truong_phong', 'pho_phong', 'chuyen_vien')
ORDER BY
    CASE u.role WHEN 'truong_phong' THEN 1 WHEN 'pho_phong' THEN 2 ELSE 3 END,
    COALESCE(m.display_order, 999),
    u.full_name
"""


def get_all_staff(db: sqlite3.Connection) -> list[dict]:
    """Tất cả nhân viên Phòng Thanh toán kèm duty meta."""
    rows = db.execute(_STAFF_SQL).fetchall()
    return [dict(r) for r in rows]


def get_staff_by_id(db: sqlite3.Connection, user_id: int) -> Optional[dict]:
    """Lấy 1 nhân viên kèm duty meta. None nếu không tìm thấy."""
    sql = _STAFF_SQL.replace(
        """ORDER BY
    CASE u.role WHEN 'truong_phong' THEN 1 WHEN 'pho_phong' THEN 2 ELSE 3 END,
    COALESCE(m.display_order, 999),
    u.full_name""",
        "AND u.id = ? ORDER BY 1"
    )
    row = db.execute(sql, (user_id,)).fetchone()
    return dict(row) if row else None


def get_absent_staff_ids(db: sqlite3.Connection, date_str: str) -> set:
    rows = db.execute(
        "SELECT staff_id FROM duty_absences WHERE absence_date = ?", (date_str,)
    ).fetchall()
    return {r["staff_id"] for r in rows}


def get_available_pool(db: sqlite3.Connection, date_str: str) -> dict:
    """
    Pool nhân viên khả dụng ngày date_str.
    Loại: đang đi dự án (is_on_project=1) và có khai báo vắng mặt.
    Trả: {'LD': [...], 'NV': [...]} — mỗi phần tử là dict nhân viên.

    Không còn nhóm 'SP' riêng: vai song phương nay suy từ cờ can_do_sp của từng
    người ngay lúc chọn tổ hợp, không bốc sẵn từ một pool tách rời.
    """
    absent_ids = get_absent_staff_ids(db, date_str)
    rows = db.execute(_STAFF_SQL).fetchall()

    pool: dict = {"LD": [], "NV": []}
    for row in rows:
        p = dict(row)
        if p["is_on_project"] or p["id"] in absent_ids:
            continue
        pool[p["duty_role"]].append(p)
    return pool


def upsert_staff_meta(
    db: sqlite3.Connection,
    user_id: int,
    can_do_sp: Optional[int] = None,
    is_on_project: Optional[int] = None,
    display_order: Optional[int] = None,
) -> dict:
    """Tạo mới hoặc cập nhật duty_staff_meta, chỉ đụng field được truyền vào."""
    now = datetime.now(_VN_TZ).replace(tzinfo=None)

    # Đọc giá trị hiện tại
    existing = db.execute(
        "SELECT * FROM duty_staff_meta WHERE user_id = ?", (user_id,)
    ).fetchone()

    if existing:
        cur = dict(existing)
        new_can_do_sp     = can_do_sp     if can_do_sp     is not None else cur["can_do_sp"]
        new_is_on_project = is_on_project if is_on_project is not None else cur["is_on_project"]
        new_display_order = display_order if display_order is not None else cur["display_order"]
        db.execute(
            "UPDATE duty_staff_meta SET can_do_sp=?, is_on_project=?, display_order=? WHERE user_id=?",
            (new_can_do_sp, new_is_on_project, new_display_order, user_id),
        )
    else:
        new_can_do_sp     = can_do_sp     or 0
        new_is_on_project = is_on_project or 0
        new_display_order = display_order or 999
        db.execute(
            "INSERT INTO duty_staff_meta (user_id, can_do_sp, is_on_project, display_order, created_at) VALUES (?,?,?,?,?)",
            (user_id, new_can_do_sp, new_is_on_project, new_display_order, now),
        )

    db.commit()
    return get_staff_by_id(db, user_id) or {}
