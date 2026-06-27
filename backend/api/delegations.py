"""Quản lý ủy quyền Giám đốc → Phó Giám đốc"""
import sqlite3
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db, _vn_now
from backend.core.deps import get_current_staff, TONG_HOP_CODES
from backend.schemas.leaves import DelegationCreate, DelegationOut

router = APIRouter()


def _deleg_to_out(d: dict, db: sqlite3.Connection) -> dict:
    def _name(staff_id):
        if not staff_id:
            return ""
        r = db.execute("SELECT full_name FROM user_tttt WHERE id = ?", (staff_id,)).fetchone()
        return r["full_name"] if r else ""

    return {
        "id":                d["id"],
        "giam_doc_id":       d["giam_doc_id"],
        "giam_doc_name":     _name(d["giam_doc_id"]),
        "pho_giam_doc_id":   d["pho_giam_doc_id"],
        "pho_giam_doc_name": _name(d["pho_giam_doc_id"]),
        "start_date":        d["start_date"],
        "end_date":          d["end_date"],
        "note":              d.get("note"),
        "is_active":         bool(d.get("is_active", 1)),
        "created_by_name":   _name(d.get("created_by_id")),
        "created_at":        d.get("created_at"),
    }


def _is_tong_hop(staff_dict: dict, db: sqlite3.Connection) -> bool:
    dept_id = staff_dict.get("department_id")
    if not dept_id:
        return False
    r = db.execute("SELECT code FROM departments WHERE id = ?", (dept_id,)).fetchone()
    return bool(r and r["code"].upper() in TONG_HOP_CODES)


@router.post("/", response_model=DelegationOut)
def create_delegation(
    body: DelegationCreate,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    if current["role"] != "admin" and not _is_tong_hop(current, db):
        raise HTTPException(403, "Chỉ Admin hoặc phòng Tổng hợp mới được tạo ủy quyền")

    gd = db.execute(
        "SELECT id FROM user_tttt WHERE id = ? AND role = 'giam_doc' AND is_active = 1",
        (body.giam_doc_id,),
    ).fetchone()
    if not gd:
        raise HTTPException(400, "Giám đốc không tồn tại hoặc không còn hoạt động")

    pgd = db.execute(
        "SELECT id FROM user_tttt WHERE id = ? AND role = 'pho_giam_doc' AND is_active = 1",
        (body.pho_giam_doc_id,),
    ).fetchone()
    if not pgd:
        raise HTTPException(400, "Phó Giám đốc không tồn tại hoặc không còn hoạt động")

    if body.end_date < body.start_date:
        raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")

    overlap = db.execute(
        """SELECT id FROM delegation_records
           WHERE pho_giam_doc_id = ? AND is_active = 1
             AND start_date <= ? AND end_date >= ?""",
        (body.pho_giam_doc_id, body.end_date.isoformat(), body.start_date.isoformat()),
    ).fetchone()
    if overlap:
        raise HTTPException(409, "PGĐ này đã có ủy quyền trong khoảng thời gian trên")

    cur = db.execute(
        """INSERT INTO delegation_records
           (giam_doc_id, pho_giam_doc_id, start_date, end_date, note, created_by_id, is_active, created_at)
           VALUES (?,?,?,?,?,?,1,?)""",
        (body.giam_doc_id, body.pho_giam_doc_id, body.start_date.isoformat(),
         body.end_date.isoformat(), body.note, current["id"], _vn_now()),
    )
    db.commit()
    row = db.execute("SELECT * FROM delegation_records WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _deleg_to_out(dict(row), db)


@router.get("/active")
def list_active_delegations(
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    """Trả về danh sách ủy quyền đang và sắp hiệu lực (không cần quyền đặc biệt)."""
    from datetime import date
    today = date.today().isoformat()
    rows = db.execute(
        """SELECT dr.*,
                  gd.full_name  AS giam_doc_name,
                  pgd.full_name AS pho_giam_doc_name
           FROM delegation_records dr
           JOIN user_tttt gd  ON dr.giam_doc_id     = gd.id
           JOIN user_tttt pgd ON dr.pho_giam_doc_id = pgd.id
           WHERE dr.is_active = 1 AND dr.end_date >= ?
           ORDER BY dr.start_date""",
        (today,)
    ).fetchall()
    return [{"id": r["id"], "giam_doc_name": r["giam_doc_name"],
             "pho_giam_doc_name": r["pho_giam_doc_name"],
             "start_date": r["start_date"], "end_date": r["end_date"],
             "note": r["note"] if r["note"] else ""} for r in rows]


@router.get("/", response_model=List[DelegationOut])
def list_delegations(
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    if current["role"] in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
        rows = db.execute(
            "SELECT * FROM delegation_records ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM delegation_records WHERE is_active = 1 ORDER BY created_at DESC"
        ).fetchall()
    return [_deleg_to_out(dict(r), db) for r in rows]


@router.patch("/{deleg_id}/deactivate", response_model=DelegationOut)
def deactivate_delegation(
    deleg_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    if current["role"] != "admin" and not _is_tong_hop(current, db):
        raise HTTPException(403, "Chỉ Admin hoặc phòng Tổng hợp mới được hủy ủy quyền")

    row = db.execute("SELECT * FROM delegation_records WHERE id = ?", (deleg_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy bản ghi ủy quyền")
    if not row["is_active"]:
        raise HTTPException(400, "Bản ghi ủy quyền đã được hủy trước đó")

    db.execute("UPDATE delegation_records SET is_active = 0 WHERE id = ?", (deleg_id,))
    db.commit()
    row = db.execute("SELECT * FROM delegation_records WHERE id = ?", (deleg_id,)).fetchone()
    return _deleg_to_out(dict(row), db)


@router.get("/staff/giam-doc")
def list_giam_doc(
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    rows = db.execute(
        "SELECT id, full_name, employee_code FROM user_tttt WHERE role = 'giam_doc' AND is_active = 1"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/staff/pho-giam-doc")
def list_pho_giam_doc(
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    rows = db.execute(
        "SELECT id, full_name, employee_code FROM user_tttt WHERE role = 'pho_giam_doc' AND is_active = 1"
    ).fetchall()
    return [dict(r) for r in rows]
