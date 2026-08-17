"""
Duty Schedule Service — CRUD ca trực, thống kê.
Raw SQLite3. Không có seed data — dùng user_tttt trực tiếp.
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from backend.services.duty_calendar_utils import week_span
from backend.services.duty_staff_service import get_all_staff
from backend.services.duty_rules import resolve_sp_role
from backend.services.duty_scheduler_engine import (
    KENH_VONG_XOAY, dieu_chinh_vong_xoay, nv_cua_ca,
    hoan_vong_xoay_cho_ca, hoan_vong_xoay_cho_ngay,
)

_VN_TZ = timezone(timedelta(hours=7))


def _now():
    return datetime.now(_VN_TZ).replace(tzinfo=None)


def _person_dict(row) -> Optional[dict]:
    if not row:
        return None
    r = dict(row)
    return {"id": r["id"], "full_name": r["full_name"], "role": r.get("role", "")}


def _lay_nguoi(db: sqlite3.Connection, ids: List[int]) -> List[dict]:
    """Đọc thông tin nhiều người, giữ đúng thứ tự đã lưu."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT id, full_name, role FROM user_tttt WHERE id IN ({placeholders})", ids
    ).fetchall()
    m = {r["id"]: _person_dict(r) for r in rows}
    return [m[i] for i in ids if i in m]


def _enrich_shift(db: sqlite3.Connection, shift_row) -> dict:
    """Bổ sung thông tin leaders, sp, nvs, nv_phu vào dict ca trực."""
    s = dict(shift_row)

    leaders = _lay_nguoi(db, json.loads(s.get("leader_ids") or "[]"))
    nvs     = _lay_nguoi(db, json.loads(s.get("nv_ids") or "[]"))
    nv_phu  = _lay_nguoi(db, json.loads(s.get("nv_phu_ids") or "[]"))

    sp = None
    if s.get("sp_id"):
        row = db.execute(
            "SELECT id, full_name, role FROM user_tttt WHERE id=?", (s["sp_id"],)
        ).fetchone()
        sp = _person_dict(row)

    return {
        "id":           s["id"],
        "shift_date":   s["shift_date"],
        "shift_type":   s["shift_type"],
        "leaders":      leaders,
        # Giữ `leader` (người đầu) cho các màn hình chỉ hiển thị một lãnh đạo
        "leader":       leaders[0] if leaders else None,
        "sp":           sp,
        "sp_warning":   s.get("sp_warning"),
        "nvs":          nvs,
        "nv_count":     s["nv_count"],
        "nv_phu":       nv_phu,
        "nv_phu_count": s.get("nv_phu_count") or 0,
        "is_auto":      bool(s["is_auto"]),
        "status":       s["status"],
        "created_at":   str(s.get("created_at") or ""),
    }


# ── READ ──────────────────────────────────────────────────────────────────────

def get_shifts_for_month(db: sqlite3.Connection, month: int, year: int,
                          status: Optional[str] = None) -> List[dict]:
    prefix = f"{year}-{month:02d}"
    sql = "SELECT * FROM duty_shifts WHERE shift_date LIKE ?"
    params: list = [f"{prefix}%"]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY shift_date, shift_type"
    rows = db.execute(sql, params).fetchall()
    return [_enrich_shift(db, r) for r in rows]


def get_shifts_for_week(db: sqlite3.Connection, start_date: str) -> List[dict]:
    t2, cn = week_span(start_date)
    rows = db.execute(
        "SELECT * FROM duty_shifts WHERE shift_date BETWEEN ? AND ? "
        "ORDER BY shift_date, shift_type",
        (t2, cn),
    ).fetchall()
    return [_enrich_shift(db, r) for r in rows]


def get_shifts_for_date(db: sqlite3.Connection, date_str: str) -> List[dict]:
    rows = db.execute(
        "SELECT * FROM duty_shifts WHERE shift_date=? ORDER BY shift_type", (date_str,)
    ).fetchall()
    return [_enrich_shift(db, r) for r in rows]


def get_shift_by_id(db: sqlite3.Connection, shift_id: int) -> Optional[dict]:
    row = db.execute("SELECT * FROM duty_shifts WHERE id=?", (shift_id,)).fetchone()
    return _enrich_shift(db, row) if row else None


# ── WRITE ─────────────────────────────────────────────────────────────────────

def update_shift(db: sqlite3.Connection, shift_id: int,
                 leader_ids: Optional[List[int]] = None,
                 nv_chinh_ids: Optional[List[int]] = None,
                 nv_phu_ids: Optional[List[int]] = None) -> Optional[dict]:
    """
    Sửa tay thành phần ca trực.
    Vai song phương tự suy từ can_do_sp — người dùng chỉ chọn người cho từng vị trí.
    Ca đã xác nhận sẽ quay về bản thảo, phải xác nhận lại.

    Caller (API) có trách nhiệm gọi validate_shift_members() trước và chặn nếu có
    lỗi luật cứng.
    """
    row = db.execute("SELECT * FROM duty_shifts WHERE id=?", (shift_id,)).fetchone()
    if not row:
        return None
    cu = dict(row)

    ld_moi    = leader_ids   if leader_ids   is not None else json.loads(cu.get("leader_ids") or "[]")
    chinh_moi = nv_chinh_ids if nv_chinh_ids is not None else list(nv_cua_ca(cu) - set(json.loads(cu.get("nv_phu_ids") or "[]")))
    phu_moi   = nv_phu_ids   if nv_phu_ids   is not None else json.loads(cu.get("nv_phu_ids") or "[]")

    # ── Xác định lại ai giữ vai song phương ──
    nhan_su  = {p["id"]: p for p in get_all_staff(db)}
    leaders  = [nhan_su[i] for i in ld_moi if i in nhan_su]
    nv_chinh = [nhan_su[i] for i in chinh_moi if i in nhan_su]
    nv_phu   = [nhan_su[i] for i in phu_moi if i in nhan_su]

    sp, sp_warning = resolve_sp_role(leaders, nv_chinh, nv_phu)
    sp_moi = sp["id"] if sp else None
    # sp_id tách khỏi nv_ids để UI hiển thị riêng, giống đường sinh tự động
    nv_luu = [i for i in chinh_moi if i != sp_moi]

    db.execute(
        "UPDATE duty_shifts SET leader_ids=?, sp_id=?, sp_warning=?, nv_ids=?, nv_count=?, "
        "nv_phu_ids=?, nv_phu_count=?, is_auto=0, status='draft' WHERE id=?",
        (json.dumps(list(ld_moi)), sp_moi, sp_warning, json.dumps(nv_luu), len(nv_luu),
         json.dumps(list(phu_moi)), len(phu_moi), shift_id),
    )

    # ── Vòng xoay đi theo người, không đi theo vị trí ──
    year = int(cu["shift_date"][:4])
    ld_role, nv_role = KENH_VONG_XOAY.get(cu["shift_type"], (None, None))
    dieu_chinh_vong_xoay(
        db, year, ld_role,
        set(json.loads(cu.get("leader_ids") or "[]")), set(ld_moi), cu["shift_date"],
    )
    dieu_chinh_vong_xoay(
        db, year, nv_role,
        nv_cua_ca(cu), set(chinh_moi) | set(phu_moi), cu["shift_date"],
    )

    db.commit()
    return get_shift_by_id(db, shift_id)


def confirm_shift(db: sqlite3.Connection, shift_id: int) -> Optional[dict]:
    cursor = db.execute(
        "UPDATE duty_shifts SET status='confirmed' WHERE id=?", (shift_id,)
    )
    db.commit()
    return get_shift_by_id(db, shift_id) if cursor.rowcount else None


def unconfirm_shift(db: sqlite3.Connection, shift_id: int) -> Optional[dict]:
    cursor = db.execute(
        "UPDATE duty_shifts SET status='draft' WHERE id=?", (shift_id,)
    )
    db.commit()
    return get_shift_by_id(db, shift_id) if cursor.rowcount else None


def confirm_shifts_for_week(db: sqlite3.Connection, week_start_str: str) -> int:
    t2, cn = week_span(week_start_str)
    cursor = db.execute(
        "UPDATE duty_shifts SET status='confirmed' "
        "WHERE shift_date BETWEEN ? AND ? AND status='draft'",
        (t2, cn),
    )
    db.commit()
    return cursor.rowcount


def delete_shifts_for_week(db: sqlite3.Connection, week_start_str: str) -> int:
    t2, cn = week_span(week_start_str)
    # Trả lại số ca đã cộng trước khi xoá, nếu không hệ thống vẫn nhớ những người
    # này đã trực và sẽ đẩy họ xuống cuối hàng ở các tuần sau.
    for row in db.execute(
        "SELECT * FROM duty_shifts WHERE shift_date BETWEEN ? AND ?", (t2, cn)
    ).fetchall():
        hoan_vong_xoay_cho_ca(db, row)

    cursor = db.execute(
        "DELETE FROM duty_shifts WHERE shift_date BETWEEN ? AND ?", (t2, cn)
    )
    db.commit()
    return cursor.rowcount


def delete_shift(db: sqlite3.Connection, shift_id: int) -> bool:
    row = db.execute("SELECT * FROM duty_shifts WHERE id=?", (shift_id,)).fetchone()
    if not row:
        return False
    hoan_vong_xoay_cho_ca(db, row)
    cursor = db.execute("DELETE FROM duty_shifts WHERE id=?", (shift_id,))
    db.commit()
    return cursor.rowcount > 0


# ── ROTATION STATE (read-only, write ở scheduler_engine) ─────────────────────

def get_rotation_state(db: sqlite3.Connection, year: int,
                        role: Optional[str] = None) -> List[dict]:
    sql = ("SELECT r.*, u.full_name AS staff_name, "
           "CASE WHEN u.role IN ('truong_phong','pho_phong') THEN 'LD' ELSE 'NV' END AS duty_role "
           "FROM duty_rotation_state r JOIN user_tttt u ON r.staff_id=u.id "
           "WHERE r.year=?")
    params: list = [year]
    if role:
        sql += " AND r.role=?"
        params.append(role)
    sql += " ORDER BY r.role, r.shift_count, r.position"
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ── STATISTICS ────────────────────────────────────────────────────────────────

def get_shift_count_by_person(db: sqlite3.Connection, year: int) -> List[dict]:
    """Số ca trực mỗi người, breakdown theo loại ca."""
    staff_rows = db.execute(
        "SELECT u.id, u.full_name, "
        "CASE WHEN u.role IN ('truong_phong','pho_phong') THEN 'LD' ELSE 'NV' END AS duty_role "
        "FROM user_tttt u JOIN departments d ON u.department_id=d.id "
        "LEFT JOIN duty_staff_meta m ON u.id=m.user_id "
        "WHERE u.is_active=1 AND u.is_deleted=0 AND d.code='PAYMENT' "
        "  AND u.role IN ('truong_phong','pho_phong','chuyen_vien') "
        "ORDER BY COALESCE(m.display_order,999), u.full_name"
    ).fetchall()

    # Chỉ đếm ca đã xác nhận — và vì mọi lần sửa đều đẩy ca về draft nên đây
    # chính là bản xác nhận cuối cùng, không cần bảng snapshot riêng.
    shift_rows = db.execute(
        "SELECT shift_type, leader_ids, sp_id, nv_ids, nv_phu_ids FROM duty_shifts "
        "WHERE shift_date LIKE ? AND status='confirmed'",
        (f"{year}-%",)
    ).fetchall()

    counts: dict = {r["id"]: {"normal": 0, "friday": 0, "cutoff": 0,
                               "settlement_main": 0, "settlement_sub": 0,
                               "truc_phu": 0}
                    for r in staff_rows}

    for shift in shift_rows:
        st = shift["shift_type"]
        # Trực chính: lãnh đạo + người song phương + nhân viên trực chính
        chinh = json.loads(shift["leader_ids"] or "[]") + json.loads(shift["nv_ids"] or "[]")
        if shift["sp_id"]:
            chinh.append(shift["sp_id"])
        for sid in chinh:
            if sid in counts:
                counts[sid][st] = counts[sid].get(st, 0) + 1
        # Trực phụ đếm riêng, không quy đổi sang ca chính
        for sid in json.loads(shift["nv_phu_ids"] or "[]"):
            if sid in counts:
                counts[sid]["truc_phu"] = counts[sid].get("truc_phu", 0) + 1

    result = []
    for r in staff_rows:
        c = counts[r["id"]]
        # Hai cột riêng, không quy đổi: trực phụ không cộng vào trực chính
        total_chinh = sum(v for k, v in c.items() if k != "truc_phu")
        result.append({
            "staff_id":   r["id"],
            "full_name":  r["full_name"],
            "duty_role":  r["duty_role"],
            **c,
            "total":       total_chinh,
            "total_chinh": total_chinh,
            "total_phu":   c["truc_phu"],
        })
    return result


def get_monthly_summary(db: sqlite3.Connection, month: int, year: int) -> dict:
    prefix = f"{year}-{month:02d}"
    rows = db.execute(
        "SELECT shift_type FROM duty_shifts WHERE shift_date LIKE ? AND status='confirmed'",
        (f"{prefix}%",)
    ).fetchall()

    by_type: dict = {}
    for r in rows:
        by_type[r["shift_type"]] = by_type.get(r["shift_type"], 0) + 1

    return {
        "month": month,
        "year": year,
        "total_shifts": len(rows),
        "by_type": by_type,
    }
