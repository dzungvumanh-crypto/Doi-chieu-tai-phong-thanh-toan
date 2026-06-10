"""
Duty Schedule Service — CRUD ca trực, thống kê.
Raw SQLite3. Không có seed data — dùng user_tttt trực tiếp.
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from backend.services.duty_calendar_utils import get_week_dates

_VN_TZ = timezone(timedelta(hours=7))


def _now():
    return datetime.now(_VN_TZ).replace(tzinfo=None)


def _person_dict(row) -> Optional[dict]:
    if not row:
        return None
    r = dict(row)
    return {"id": r["id"], "full_name": r["full_name"], "role": r.get("role", "")}


def _enrich_shift(db: sqlite3.Connection, shift_row) -> dict:
    """Bổ sung thông tin leader, sp, nvs vào dict ca trực."""
    s = dict(shift_row)

    leader = None
    if s.get("leader_id"):
        row = db.execute(
            "SELECT id, full_name, role FROM user_tttt WHERE id=?", (s["leader_id"],)
        ).fetchone()
        leader = _person_dict(row)

    sp = None
    if s.get("sp_id"):
        row = db.execute(
            "SELECT id, full_name, role FROM user_tttt WHERE id=?", (s["sp_id"],)
        ).fetchone()
        sp = _person_dict(row)

    nv_id_list = json.loads(s.get("nv_ids") or "[]")
    nvs = []
    if nv_id_list:
        placeholders = ",".join("?" * len(nv_id_list))
        rows = db.execute(
            f"SELECT id, full_name, role FROM user_tttt WHERE id IN ({placeholders})",
            nv_id_list
        ).fetchall()
        nv_map = {r["id"]: _person_dict(r) for r in rows}
        nvs = [nv_map[nid] for nid in nv_id_list if nid in nv_map]

    return {
        "id":          s["id"],
        "shift_date":  s["shift_date"],
        "shift_type":  s["shift_type"],
        "leader":      leader,
        "sp":          sp,
        "sp_warning":  s.get("sp_warning"),
        "nvs":         nvs,
        "nv_count":    s["nv_count"],
        "is_auto":     bool(s["is_auto"]),
        "status":      s["status"],
        "created_at":  str(s.get("created_at") or ""),
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
    dates = get_week_dates(start_date)
    placeholders = ",".join("?" * len(dates))
    rows = db.execute(
        f"SELECT * FROM duty_shifts WHERE shift_date IN ({placeholders}) ORDER BY shift_date, shift_type",
        dates
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
                 leader_id: Optional[int] = None,
                 sp_id: Optional[int] = None,
                 nv_ids: Optional[List[int]] = None) -> Optional[dict]:
    row = db.execute("SELECT id FROM duty_shifts WHERE id=?", (shift_id,)).fetchone()
    if not row:
        return None

    sets = ["is_auto=0"]
    params: list = []

    if leader_id is not None:
        sets.append("leader_id=?")
        params.append(leader_id)
    if sp_id is not None:
        sets.append("sp_id=?")
        params.append(sp_id)
    if nv_ids is not None:
        sets.append("nv_ids=?")
        sets.append("nv_count=?")
        params.extend([json.dumps(nv_ids), len(nv_ids)])

    params.append(shift_id)
    db.execute(f"UPDATE duty_shifts SET {', '.join(sets)} WHERE id=?", params)
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
    dates = get_week_dates(week_start_str)
    placeholders = ",".join("?" * len(dates))
    cursor = db.execute(
        f"UPDATE duty_shifts SET status='confirmed' WHERE shift_date IN ({placeholders}) AND status='draft'",
        dates
    )
    db.commit()
    return cursor.rowcount


def delete_shifts_for_week(db: sqlite3.Connection, week_start_str: str) -> int:
    dates = get_week_dates(week_start_str)
    placeholders = ",".join("?" * len(dates))
    cursor = db.execute(
        f"DELETE FROM duty_shifts WHERE shift_date IN ({placeholders})", dates
    )
    db.commit()
    return cursor.rowcount


def delete_shift(db: sqlite3.Connection, shift_id: int) -> bool:
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

    shift_rows = db.execute(
        "SELECT shift_type, leader_id, sp_id, nv_ids FROM duty_shifts "
        "WHERE shift_date LIKE ? AND status='confirmed'",
        (f"{year}-%",)
    ).fetchall()

    counts: dict = {r["id"]: {"normal": 0, "friday": 0, "cutoff": 0,
                               "settlement_main": 0, "settlement_sub": 0}
                    for r in staff_rows}

    for shift in shift_rows:
        st = shift["shift_type"]
        if shift["leader_id"] and shift["leader_id"] in counts:
            counts[shift["leader_id"]][st] = counts[shift["leader_id"]].get(st, 0) + 1
        if shift["sp_id"] and shift["sp_id"] in counts:
            counts[shift["sp_id"]][st] = counts[shift["sp_id"]].get(st, 0) + 1
        for nv_id in json.loads(shift["nv_ids"] or "[]"):
            if nv_id in counts:
                counts[nv_id][st] = counts[nv_id].get(st, 0) + 1

    result = []
    for r in staff_rows:
        c = counts[r["id"]]
        total = sum(c.values())
        result.append({
            "staff_id":   r["id"],
            "full_name":  r["full_name"],
            "duty_role":  r["duty_role"],
            **c,
            "total": total,
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
