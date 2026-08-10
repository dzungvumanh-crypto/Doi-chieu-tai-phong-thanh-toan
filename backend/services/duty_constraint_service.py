"""
Duty Constraint Service — vắng mặt, đăng ký xin trực, ngày đặc biệt, cấu hình ca.
Raw SQLite3, không ORM.
"""
import json
import sqlite3
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional

from backend.services.duty_rules import MAC_DINH_COT

_VN_TZ = timezone(timedelta(hours=7))
DEFAULT_NV_COUNT = 2


def _now():
    return datetime.now(_VN_TZ).replace(tzinfo=None)


# ══════════════════════════════════════════════════════════════
# ABSENCES
# ══════════════════════════════════════════════════════════════

def list_absences(db: sqlite3.Connection, month: Optional[int] = None,
                  year: Optional[int] = None) -> List[dict]:
    if month and year:
        prefix = f"{year}-{month:02d}"
        rows = db.execute(
            "SELECT a.*, u.full_name AS staff_name FROM duty_absences a "
            "LEFT JOIN user_tttt u ON a.staff_id = u.id "
            "WHERE a.absence_date LIKE ? ORDER BY a.absence_date",
            (f"{prefix}%",)
        ).fetchall()
    elif year:
        rows = db.execute(
            "SELECT a.*, u.full_name AS staff_name FROM duty_absences a "
            "LEFT JOIN user_tttt u ON a.staff_id = u.id "
            "WHERE a.absence_date LIKE ? ORDER BY a.absence_date",
            (f"{year}%",)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT a.*, u.full_name AS staff_name FROM duty_absences a "
            "LEFT JOIN user_tttt u ON a.staff_id = u.id ORDER BY a.absence_date"
        ).fetchall()
    return [dict(r) for r in rows]


def create_absence(db: sqlite3.Connection, staff_id: int, absence_date: str) -> dict:
    existing = db.execute(
        "SELECT * FROM duty_absences WHERE staff_id=? AND absence_date=?",
        (staff_id, absence_date)
    ).fetchone()
    if existing:
        return dict(existing)
    db.execute(
        "INSERT INTO duty_absences (staff_id, absence_date, created_at) VALUES (?,?,?)",
        (staff_id, absence_date, _now())
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM duty_absences WHERE staff_id=? AND absence_date=?",
        (staff_id, absence_date)
    ).fetchone()
    return dict(row)


def create_absence_range(db: sqlite3.Connection, staff_id: int,
                         from_date: str, to_date: str) -> dict:
    start = date.fromisoformat(from_date)
    end   = date.fromisoformat(to_date)
    created = 0
    skipped = 0
    d = start
    while d <= end:
        ds = d.isoformat()
        existing = db.execute(
            "SELECT id FROM duty_absences WHERE staff_id=? AND absence_date=?",
            (staff_id, ds)
        ).fetchone()
        if existing:
            skipped += 1
        else:
            db.execute(
                "INSERT INTO duty_absences (staff_id, absence_date, created_at) VALUES (?,?,?)",
                (staff_id, ds, _now())
            )
            created += 1
        d += timedelta(days=1)
    db.commit()
    return {"created": created, "skipped": skipped}


def delete_absence_range(db: sqlite3.Connection, staff_id: int,
                         from_date: str, to_date: str) -> dict:
    cursor = db.execute(
        "DELETE FROM duty_absences WHERE staff_id=? AND absence_date>=? AND absence_date<=?",
        (staff_id, from_date, to_date)
    )
    db.commit()
    return {"deleted": cursor.rowcount}


def delete_absence(db: sqlite3.Connection, absence_id: int) -> bool:
    cursor = db.execute("DELETE FROM duty_absences WHERE id=?", (absence_id,))
    db.commit()
    return cursor.rowcount > 0


# ══════════════════════════════════════════════════════════════
# DUTY REQUESTS
# ══════════════════════════════════════════════════════════════

def list_requests(db: sqlite3.Connection, year: Optional[int] = None,
                  staff_id: Optional[int] = None) -> List[dict]:
    sql = ("SELECT r.*, u.full_name AS staff_name FROM duty_requests r "
           "LEFT JOIN user_tttt u ON r.staff_id = u.id WHERE r.is_active=1")
    params: list = []
    if year:
        sql += " AND r.year=?"
        params.append(year)
    if staff_id:
        sql += " AND r.staff_id=?"
        params.append(staff_id)
    sql += " ORDER BY r.id"
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_requests_for_date(db: sqlite3.Connection, date_str: str, year: int) -> dict:
    """
    Trả {'LD': [...], 'SP': [...], 'NV': [...], 'once_ids': set()}
    Kết hợp đăng ký 'once' và 'weekly'.
    """
    dow = date.fromisoformat(date_str).weekday()

    rows = db.execute(
        "SELECT * FROM duty_requests WHERE is_active=1 AND year=?", (year,)
    ).fetchall()

    staff_ids: set = set()
    once_staff_ids: set = set()
    for r in rows:
        if r["request_type"] == "once" and r["specific_date"] == date_str:
            staff_ids.add(r["staff_id"])
            once_staff_ids.add(r["staff_id"])
        elif r["request_type"] == "weekly" and r["day_of_week"] == dow:
            staff_ids.add(r["staff_id"])

    result: dict = {"LD": [], "SP": [], "NV": [], "once_ids": set()}
    if not staff_ids:
        return result

    placeholders = ",".join("?" * len(staff_ids))
    people = db.execute(
        f"SELECT u.id, "
        f"CASE WHEN u.role IN ('truong_phong','pho_phong') THEN 'LD' ELSE 'NV' END AS duty_role, "
        f"COALESCE(m.can_do_sp, 0) AS can_do_sp "
        f"FROM user_tttt u LEFT JOIN duty_staff_meta m ON u.id=m.user_id "
        f"WHERE u.id IN ({placeholders})",
        list(staff_ids)
    ).fetchall()

    for p in people:
        if p["duty_role"] == "LD":
            result["LD"].append(p["id"])
        else:
            result["NV"].append(p["id"])
            if p["can_do_sp"]:
                result["SP"].append(p["id"])
        if p["id"] in once_staff_ids:
            result["once_ids"].add(p["id"])

    return result


def create_request(db: sqlite3.Connection, staff_id: int, request_type: str,
                   year: int, specific_date: Optional[str] = None,
                   day_of_week: Optional[int] = None) -> dict:
    # Idempotent
    existing = db.execute(
        "SELECT * FROM duty_requests WHERE staff_id=? AND request_type=? AND specific_date IS ? "
        "AND day_of_week IS ? AND year=? AND is_active=1",
        (staff_id, request_type, specific_date, day_of_week, year)
    ).fetchone()
    if existing:
        return dict(existing)

    # Từ chối đăng ký T7/CN và ngày lễ
    if request_type == "once" and specific_date:
        d = date.fromisoformat(specific_date)
        if d.weekday() >= 5:
            raise ValueError(f"Không thể đăng ký cuối tuần ({specific_date})")
        holiday = db.execute(
            "SELECT label FROM duty_special_days WHERE date=? AND day_type='holiday'",
            (specific_date,)
        ).fetchone()
        if holiday:
            label = f" ({holiday['label']})" if holiday["label"] else ""
            raise ValueError(f"Không thể đăng ký ngày lễ{label} ({specific_date})")

    db.execute(
        "INSERT INTO duty_requests (staff_id, request_type, specific_date, day_of_week, year, is_active, created_at) VALUES (?,?,?,?,?,1,?)",
        (staff_id, request_type, specific_date, day_of_week, year, _now())
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM duty_requests WHERE staff_id=? AND request_type=? AND specific_date IS ? "
        "AND day_of_week IS ? AND year=? AND is_active=1",
        (staff_id, request_type, specific_date, day_of_week, year)
    ).fetchone()
    return dict(row)


def delete_request(db: sqlite3.Connection, request_id: int) -> bool:
    cursor = db.execute("DELETE FROM duty_requests WHERE id=?", (request_id,))
    db.commit()
    return cursor.rowcount > 0


# ══════════════════════════════════════════════════════════════
# SPECIAL DAYS
# ══════════════════════════════════════════════════════════════

def list_special_days(db: sqlite3.Connection, month: Optional[int] = None,
                      year: Optional[int] = None,
                      day_type: Optional[str] = None) -> List[dict]:
    sql = "SELECT * FROM duty_special_days WHERE 1=1"
    params: list = []
    if month and year:
        sql += " AND date LIKE ?"
        params.append(f"{year}-{month:02d}%")
    elif year:
        sql += " AND date LIKE ?"
        params.append(f"{year}%")
    if day_type:
        sql += " AND day_type=?"
        params.append(day_type)
    sql += " ORDER BY date"
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_holiday_dates(db: sqlite3.Connection, year: int) -> set:
    rows = db.execute(
        "SELECT date FROM duty_special_days WHERE day_type='holiday' AND date LIKE ?",
        (f"{year}%",)
    ).fetchall()
    return {r["date"] for r in rows}


def get_special_day(db: sqlite3.Connection, date_str: str) -> Optional[dict]:
    row = db.execute(
        "SELECT * FROM duty_special_days WHERE date=?", (date_str,)
    ).fetchone()
    return dict(row) if row else None


def create_special_day(db: sqlite3.Connection, date_str: str, day_type: str,
                       label: Optional[str] = None, is_confirmed: int = 0) -> dict:
    existing = db.execute(
        "SELECT * FROM duty_special_days WHERE date=?", (date_str,)
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE duty_special_days SET day_type=?, label=COALESCE(?, label) WHERE date=?",
            (day_type, label, date_str)
        )
        db.commit()
        row = db.execute("SELECT * FROM duty_special_days WHERE date=?", (date_str,)).fetchone()
        return dict(row)
    db.execute(
        "INSERT INTO duty_special_days (date, day_type, label, is_confirmed, created_at) VALUES (?,?,?,?,?)",
        (date_str, day_type, label, is_confirmed, _now())
    )
    db.commit()
    row = db.execute("SELECT * FROM duty_special_days WHERE date=?", (date_str,)).fetchone()
    return dict(row)


def confirm_special_day(db: sqlite3.Connection, special_day_id: int) -> Optional[dict]:
    cursor = db.execute(
        "UPDATE duty_special_days SET is_confirmed=1 WHERE id=?", (special_day_id,)
    )
    db.commit()
    if cursor.rowcount == 0:
        return None
    row = db.execute("SELECT * FROM duty_special_days WHERE id=?", (special_day_id,)).fetchone()
    return dict(row)


def delete_special_day(db: sqlite3.Connection, special_day_id: int) -> dict:
    row = db.execute("SELECT * FROM duty_special_days WHERE id=?", (special_day_id,)).fetchone()
    if not row:
        return {"deleted": False, "warning": None}

    confirmed_count = db.execute(
        "SELECT COUNT(*) FROM duty_shifts WHERE shift_date=? AND status='confirmed'",
        (row["date"],)
    ).fetchone()[0]

    warning = None
    if confirmed_count > 0:
        warning = (
            f"Ngày {row['date']} đang có {confirmed_count} ca đã xác nhận. "
            "Ca đó vẫn được giữ nguyên sau khi xóa ngày đặc biệt."
        )

    db.execute("DELETE FROM duty_special_days WHERE id=?", (special_day_id,))
    db.commit()
    return {"deleted": True, "warning": warning}


def upsert_special_days_bulk(db: sqlite3.Connection, days: List[dict]) -> List[dict]:
    result = []
    for d in days:
        obj = create_special_day(
            db, d["date"], d["day_type"],
            label=d.get("label"), is_confirmed=d.get("is_confirmed", 0)
        )
        result.append(obj)
    return result


# ══════════════════════════════════════════════════════════════
# SHIFT CONFIG
# ══════════════════════════════════════════════════════════════

def get_shift_config(db: sqlite3.Connection, year: int) -> Optional[dict]:
    row = db.execute(
        "SELECT * FROM duty_shift_config WHERE year=?", (year,)
    ).fetchone()
    return dict(row) if row else None


def upsert_shift_config(db: sqlite3.Connection, year: int,
                        nv_count: Optional[int] = None,
                        signer_name: Optional[str] = None,
                        ld_count: Optional[int] = None,
                        qt_ld_count: Optional[int] = None,
                        qt_nv_chinh_count: Optional[int] = None,
                        qt_nv_phu_count: Optional[int] = None) -> dict:
    """Ghi cấu hình số người mỗi ca. Trường nào không truyền thì GIỮ NGUYÊN.

    Trước đây các tham số có giá trị mặc định và câu UPDATE ghi thẳng — client
    chỉ gửi nv_count là cấu hình ca quyết toán bị reset về 1/3/2 mà không báo gì.
    """
    cot = {"ld_count": ld_count, "nv_count": nv_count, "qt_ld_count": qt_ld_count,
           "qt_nv_chinh_count": qt_nv_chinh_count, "qt_nv_phu_count": qt_nv_phu_count}

    existing = db.execute(
        "SELECT * FROM duty_shift_config WHERE year=?", (year,)
    ).fetchone()
    if existing:
        gan = ", ".join(f"{k}=COALESCE(?, {k})" for k in cot)
        db.execute(
            f"UPDATE duty_shift_config SET {gan}, "
            f"signer_name=COALESCE(?, signer_name) WHERE year=?",
            (*cot.values(), signer_name, year)
        )
    else:
        # Năm mới: trường không gửi lấy mặc định nghiệp vụ, không để NULL
        gia_tri = [v if v is not None else MAC_DINH_COT[k] for k, v in cot.items()]
        db.execute(
            f"INSERT INTO duty_shift_config (year, {', '.join(cot)}, signer_name) "
            f"VALUES (?,?,?,?,?,?,?)",
            (year, *gia_tri, signer_name)
        )
    db.commit()
    row = db.execute("SELECT * FROM duty_shift_config WHERE year=?", (year,)).fetchone()
    return dict(row)


# ══════════════════════════════════════════════════════════════
# WEEK ASSIGNEES
# ══════════════════════════════════════════════════════════════

def get_week_assignees(db: sqlite3.Connection, date_str: str) -> set:
    """
    Trả set staff_id đã được phân trực trong tuần (từ T2 đến trước date_str).
    Dùng để tránh phân cùng người 2 lần trong 1 tuần.
    """
    d = date.fromisoformat(date_str)
    week_start = d - timedelta(days=d.weekday())
    if week_start >= d:
        return set()

    shifts = db.execute(
        "SELECT leader_ids, sp_id, nv_ids, nv_phu_ids FROM duty_shifts "
        "WHERE shift_date >= ? AND shift_date < ? AND status IN ('confirmed','draft')",
        (week_start.isoformat(), date_str)
    ).fetchall()

    ids: set = set()
    for s in shifts:
        if s["sp_id"]:
            ids.add(s["sp_id"])
        for cot in ("leader_ids", "nv_ids", "nv_phu_ids"):
            ids.update(json.loads(s[cot] or "[]"))
    return ids
