"""KSNB Staff management endpoints"""
import io
import os
import sqlite3
import tempfile
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from backend.database import DB_PATH, get_db, write_audit, compute_annual_leave, _vn_now

# Mốc hiệu lực gốc cho dòng lịch sử phòng đầu tiên của mỗi cán bộ
_DEPT_HISTORY_EPOCH = "2000-01-01"
from backend.schemas.staff import StaffCreate, StaffUpdate, StaffOut
from backend.core.security import get_password_hash
from backend.core.deps import get_current_staff, require_feature

router = APIRouter(prefix="/api/staff", tags=["Staff"])

# Quản trị viên (cấp 1 + cấp 2) — không thuộc phòng nào
_ADMIN_ROLES = frozenset(("admin", "admin_l2"))
# Role được xem toàn bộ nhân viên không bị giới hạn phòng
_BROAD_VIEW_ROLES = frozenset(("admin", "admin_l2", "hau_kiem_vien", "giam_doc", "pho_giam_doc"))

_ROLE_ORDER_SQL = """
    CASE role
        WHEN 'giam_doc'      THEN 0
        WHEN 'pho_giam_doc'  THEN 1
        WHEN 'admin'         THEN 2
        WHEN 'admin_l2'      THEN 3
        WHEN 'truong_phong'  THEN 4
        WHEN 'pho_phong'     THEN 5
        WHEN 'hau_kiem_vien' THEN 6
        WHEN 'chuyen_vien'   THEN 7
        ELSE 9
    END
"""


def _validate_dept(db: sqlite3.Connection, role: str, department_id):
    # Quản trị viên (cấp 1 + cấp 2) không thuộc phòng nào — bỏ qua yêu cầu chọn phòng
    if role in _ADMIN_ROLES:
        return
    if not department_id:
        raise HTTPException(400, "Phải chọn phòng ban")
    dept = db.execute(
        "SELECT * FROM departments WHERE id = ? AND is_active = 1", (department_id,)
    ).fetchone()
    if not dept:
        raise HTTPException(400, "Phòng ban không tồn tại hoặc không còn hoạt động")
    if role in ("giam_doc", "pho_giam_doc") and dept["is_source"]:
        raise HTTPException(400, "Giám đốc / Phó Giám đốc phải thuộc Ban Giám đốc")


@router.get("/", response_model=List[StaffOut])
def list_staff(
    active_only: bool = True,
    department_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    clauses = ["(is_deleted = 0 OR is_deleted IS NULL)"]
    params = []
    if active_only:
        clauses.append("is_active = 1")

    # ── Scope theo role ──
    is_broad = current["role"] in _BROAD_VIEW_ROLES
    if not is_broad:
        # Kiểm tra có phải nhân viên phòng Tổng hợp không (cần xem GĐ/PGĐ để chọn approver)
        dept_row = db.execute(
            "SELECT code FROM departments WHERE id = ?", (current.get("department_id"),)
        ).fetchone() if current.get("department_id") else None
        is_broad = bool(dept_row and dept_row["code"].upper() in ("TH", "TONGHOP", "TONG_HOP"))

    if not is_broad:
        # truong_phong / pho_phong / chuyen_vien: chỉ xem phòng mình
        own_dept = current.get("department_id")
        if own_dept:
            clauses.append("department_id = ?")
            params.append(own_dept)
    elif department_id:
        # Broad role: filter theo phòng nếu client yêu cầu
        clauses.append("department_id = ?")
        params.append(department_id)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(
        f"SELECT * FROM user_tttt {where} ORDER BY {_ROLE_ORDER_SQL}, full_name", params
    ).fetchall()
    return [_enrich(dict(r)) for r in rows]


# ─── Export Excel / Import DB ────────────────────────────────────────────────
# Đặt trước /{staff_id} để tránh FastAPI match "export" như int

_ROLE_VN = {
    "chuyen_vien":   "Chuyên viên",
    "pho_phong":     "Phó phòng",
    "truong_phong":  "Trưởng phòng",
    "hau_kiem_vien": "Hậu kiểm viên",
    "giam_doc":      "Giám đốc",
    "pho_giam_doc":  "Phó Giám đốc",
    "admin":         "Quản trị viên cấp 1",
    "admin_l2":      "Quản trị viên cấp 2",
    "controller":    "Phó phòng",
}


@router.get("/export")
def export_staff_excel(
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(require_feature("staff.export")),
):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from datetime import date, datetime as _dt

    rows = db.execute("""
        SELECT u.full_name, u.employee_code, u.role, d.name AS dept_name,
               u.username, u.ipcas_code, u.payment_username, u.phone,
               u.is_active, u.created_at
        FROM user_tttt u
        LEFT JOIN departments d ON u.department_id = d.id
        WHERE u.is_deleted = 0 OR u.is_deleted IS NULL
        ORDER BY d.name, u.full_name
    """).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Danh sách cán bộ"

    hdr_fill = PatternFill("solid", fgColor="C62828")
    hdr_font = Font(bold=True, color="FFFFFF")
    headers = ["STT", "Họ và tên", "Mã cán bộ", "Quyền", "Phòng", "Username",
               "User IPCAS", "User Payment", "Điện thoại", "Trạng thái", "Ngày tạo"]
    widths   = [6, 28, 14, 18, 24, 18, 14, 20, 14, 12, 14]
    ws.append(headers)
    for cell, w in zip(ws[1], widths):
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, r in enumerate(rows, 1):
        created = ""
        try:
            created = _dt.fromisoformat(str(r["created_at"])).strftime("%d/%m/%Y")
        except Exception:
            pass
        ws.append([
            idx,
            r["full_name"] or "",
            r["employee_code"] or "",
            _ROLE_VN.get(r["role"], r["role"]),
            r["dept_name"] or "",
            r["username"] or "",
            r["ipcas_code"] or "",
            r["payment_username"] or "",
            r["phone"] or "",
            "Hoạt động" if r["is_active"] else "Tạm khóa",
            created,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"danh_sach_can_bo_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )


@router.get("/export-db")
def export_users_db(_: dict = Depends(require_feature("staff.export"))):
    """Xuất bảng user_tttt thành file SQLite để chép sang hệ thống khác."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        src = sqlite3.connect(DB_PATH)
        exp = sqlite3.connect(tmp.name)
        ddl = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='user_tttt'"
        ).fetchone()[0]
        exp.execute(ddl)
        src.row_factory = sqlite3.Row
        rows_db = src.execute(
            "SELECT * FROM user_tttt WHERE is_deleted = 0 OR is_deleted IS NULL"
        ).fetchall()
        if rows_db:
            cols = list(rows_db[0].keys())
            ph = ",".join("?" * len(cols))
            exp.executemany(f"INSERT INTO user_tttt VALUES ({ph})", [tuple(r) for r in rows_db])
        exp.commit()
        src.close()
        exp.close()
        data = open(tmp.name, "rb").read()
    finally:
        os.unlink(tmp.name)

    from datetime import date as _date
    fname_db = f"users_{_date.today().strftime('%Y%m%d')}.db"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fname_db}"'},
    )


def _enrich(row: dict) -> dict:
    """Inject annual_leave_days tính từ join_industry_date nếu có."""
    if row.get("join_industry_date"):
        row["annual_leave_days"] = compute_annual_leave(row["join_industry_date"])
    return row


@router.get("/{staff_id}", response_model=StaffOut)
def get_staff(
    staff_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    row = db.execute("SELECT * FROM user_tttt WHERE id = ?", (staff_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    return _enrich(dict(row))


@router.post("/", response_model=StaffOut)
def create_staff(
    body: StaffCreate,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("staff.create")),
):
    if db.execute("SELECT id FROM user_tttt WHERE username = ?", (body.username,)).fetchone():
        raise HTTPException(400, "Username đã tồn tại")
    emp_code = body.employee_code or body.username
    if db.execute("SELECT id FROM user_tttt WHERE employee_code = ?", (emp_code,)).fetchone():
        raise HTTPException(400, "Mã nhân viên đã tồn tại")
    # QTV cấp 2 không được tạo QTV cấp 1 (tránh leo thang quyền)
    if current["role"] == "admin_l2" and body.role == "admin":
        raise HTTPException(403, "Quản trị viên cấp 2 không được tạo Quản trị viên cấp 1")
    # Admin (cấp 1 + cấp 2) không thuộc phòng nào → ép department_id về None dù client có gửi
    dept_id = None if body.role in _ADMIN_ROLES else body.department_id
    _validate_dept(db, body.role, dept_id)
    join_date_iso = body.join_industry_date.isoformat() if body.join_industry_date else None
    cur = db.execute(
        """INSERT INTO user_tttt
           (employee_code, full_name, role, department_id, username, pwd_hash,
            phone, email, start_date, join_industry_date, ipcas_code, payment_username, is_active)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
        (emp_code, body.full_name, body.role, dept_id, body.username,
         get_password_hash(body.password), body.phone, body.email,
         body.start_date.isoformat() if body.start_date else None,
         join_date_iso, body.ipcas_code, body.payment_username),
    )
    new_id = cur.lastrowid
    # Dòng lịch sử phòng đầu tiên — hiệu lực từ epoch để phủ mọi tháng trước đó
    if dept_id:
        db.execute(
            "INSERT INTO staff_department_history (staff_id, department_id, effective_from, created_at) VALUES (?,?,?,?)",
            (new_id, dept_id, _DEPT_HISTORY_EPOCH, str(_vn_now())),
        )
    client_ip = request.client.host if request.client else "unknown"
    write_audit(db, current["id"], "staff_create", "staff", new_id,
                f"Tạo tài khoản {body.username} ({body.full_name})", client_ip)
    db.commit()
    row = db.execute("SELECT * FROM user_tttt WHERE id = ?", (new_id,)).fetchone()
    return _enrich(dict(row))


@router.put("/{staff_id}", response_model=StaffOut)
def update_staff(
    staff_id: int,
    body: StaffUpdate,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("staff.edit")),
):
    row = db.execute("SELECT * FROM user_tttt WHERE id = ?", (staff_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    # QTV cấp 2 không được đụng tài khoản cấp 1, cũng không được nâng ai lên cấp 1
    if current["role"] == "admin_l2":
        if row["role"] == "admin":
            raise HTTPException(403, "Quản trị viên cấp 2 không được sửa tài khoản Quản trị viên cấp 1")
        if body.role == "admin":
            raise HTTPException(403, "Quản trị viên cấp 2 không được nâng lên Quản trị viên cấp 1")
    update_data = body.dict(exclude_none=True)
    # Serialize date object → ISO string cho sqlite3
    if "join_industry_date" in update_data and update_data["join_industry_date"]:
        update_data["join_industry_date"] = update_data["join_industry_date"].isoformat()
    if "employee_code" in update_data:
        dup = db.execute(
            "SELECT id FROM user_tttt WHERE employee_code = ? AND id != ?",
            (update_data["employee_code"], staff_id),
        ).fetchone()
        if dup:
            raise HTTPException(400, "Mã cán bộ đã tồn tại")
    new_role = update_data.get("role", row["role"])
    new_dept = update_data.get("department_id", row["department_id"])
    # Admin (cấp 1 + cấp 2) không thuộc phòng nào → ép department_id về None
    if new_role in _ADMIN_ROLES:
        new_dept = None
        update_data["department_id"] = None
    _validate_dept(db, new_role, new_dept)
    if update_data:
        sets = ", ".join(f"{k} = ?" for k in update_data)
        params = list(update_data.values()) + [staff_id]
        db.execute(f"UPDATE user_tttt SET {sets} WHERE id = ?", params)
        # Đổi phòng → ghi mốc lịch sử, hiệu lực từ ngày quản trị viên thực hiện (hôm nay)
        # Bỏ qua khi chuyển sang admin (new_dept = None) vì history.department_id NOT NULL
        if new_dept != row["department_id"] and new_dept:
            db.execute(
                "INSERT INTO staff_department_history (staff_id, department_id, effective_from, created_at) VALUES (?,?,?,?)",
                (staff_id, new_dept, _vn_now().date().isoformat(), str(_vn_now())),
            )
        client_ip = request.client.host if request.client else "unknown"
        changed = ", ".join(f"{k}={v}" for k, v in update_data.items() if k != "pwd_hash")
        write_audit(db, current["id"], "staff_update", "staff", staff_id,
                    f"Cập nhật {row['username']}: {changed}", client_ip)
        db.commit()
    row = db.execute("SELECT * FROM user_tttt WHERE id = ?", (staff_id,)).fetchone()
    return _enrich(dict(row))


@router.delete("/{staff_id}")
def delete_staff(
    staff_id: int,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("staff.delete")),
):
    if staff_id == current["id"]:
        raise HTTPException(400, "Không thể xóa tài khoản của chính mình")
    row = db.execute("SELECT username, full_name, role FROM user_tttt WHERE id = ?", (staff_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    if current["role"] == "admin_l2" and row["role"] == "admin":
        raise HTTPException(403, "Quản trị viên cấp 2 không được xóa tài khoản Quản trị viên cấp 1")
    db.execute("UPDATE user_tttt SET is_deleted = 1, is_active = 0 WHERE id = ?", (staff_id,))
    client_ip = request.client.host if request.client else "unknown"
    write_audit(db, current["id"], "staff_delete", "staff", staff_id,
                f"Xóa tài khoản {row['username']} ({row['full_name']})", client_ip)
    db.commit()
    return {"message": "Đã xóa tài khoản"}


@router.post("/import-db")
def import_users_db(
    file: UploadFile = File(...),
    request: Request = None,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("staff.import_db")),
):
    """Nhập bảng user_tttt từ file SQLite xuất bởi hệ thống cùng schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        tmp.write(file.file.read())
        tmp.close()
        imp = sqlite3.connect(tmp.name)
        imp.row_factory = sqlite3.Row
        rows = imp.execute("SELECT * FROM user_tttt").fetchall()
        imp.close()
    finally:
        os.unlink(tmp.name)

    if not rows:
        raise HTTPException(400, "File không có dữ liệu user_tttt")

    cols = list(rows[0].keys())
    non_id_cols = [c for c in cols if c != "id"]
    inserted = updated = 0
    db.execute("PRAGMA foreign_keys = OFF")
    for row in rows:
        existing = db.execute(
            "SELECT id FROM user_tttt WHERE employee_code = ?", (row["employee_code"],)
        ).fetchone()
        vals = [row[c] for c in non_id_cols]
        if existing:
            sets = ", ".join(f"{c} = ?" for c in non_id_cols if c != "employee_code")
            set_vals = [row[c] for c in non_id_cols if c != "employee_code"]
            db.execute(
                f"UPDATE user_tttt SET {sets} WHERE employee_code = ?",
                set_vals + [row["employee_code"]],
            )
            updated += 1
        else:
            ph = ",".join("?" * len(non_id_cols))
            db.execute(
                f"INSERT INTO user_tttt ({','.join(non_id_cols)}) VALUES ({ph})", vals
            )
            inserted += 1
    db.execute("PRAGMA foreign_keys = ON")
    db.commit()
    client_ip = request.client.host if request and request.client else "unknown"
    write_audit(db, current["id"], "staff_import_db", "staff", None,
                f"Import DB: +{inserted} mới, ~{updated} cập nhật", client_ip)
    db.commit()
    return {"inserted": inserted, "updated": updated}


# ─── Leave records (DEPRECATED — dùng /api/leaves/ thay thế) ────────────────
@router.get("/{staff_id}/leaves", deprecated=True)
def list_leaves_deprecated(
    staff_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    rows = db.execute(
        "SELECT * FROM leave_records WHERE staff_id = ? ORDER BY start_date DESC", (staff_id,)
    ).fetchall()
    return [dict(r) for r in rows]
