"""Authentication endpoints"""
import logging
import re
import sqlite3
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from backend.database import get_db, _vn_now, write_audit
from backend.schemas.auth import LoginRequest, Token, PasswordChange, AdminPasswordReset
from backend.core.security import verify_password, create_access_token, get_password_hash
from backend.core.deps import get_current_staff, require_admin
from backend.core.sessions import set_session, get_session_ip, clear_session
from backend.core.config import settings
from backend.core import rate_limit

router = APIRouter(prefix="/api/auth", tags=["Auth"])
_log = logging.getLogger("auth")

_PWD_RE = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z\d]).{8,}$')


def _validate_password(pwd: str):
    if len(pwd) < 8:
        raise HTTPException(400, "Mật khẩu phải có ít nhất 8 ký tự")
    if not re.search(r'[A-Z]', pwd):
        raise HTTPException(400, "Mật khẩu phải có ít nhất 1 chữ hoa")
    if not re.search(r'[a-z]', pwd):
        raise HTTPException(400, "Mật khẩu phải có ít nhất 1 chữ thường")
    if not re.search(r'\d', pwd):
        raise HTTPException(400, "Mật khẩu phải có ít nhất 1 chữ số")
    if not re.search(r'[^a-zA-Z\d]', pwd):
        raise HTTPException(400, "Mật khẩu phải có ít nhất 1 ký tự đặc biệt")


@router.post("/login", response_model=Token)
def login(req: LoginRequest, request: Request, db: sqlite3.Connection = Depends(get_db)):
    # ── Rate limit ──
    wait = rate_limit.seconds_locked(db, req.username)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Quá nhiều lần đăng nhập sai. Thử lại sau {wait} giây.",
        )

    # X-Client-IP do NiceGUI frontend chuyển tiếp — IP thật của browser
    client_ip = (
        request.headers.get("X-Client-IP", "").strip()
        or (request.client.host if request.client else "unknown")
    )
    _log.info("login attempt user=%r x_client_ip=%r fastapi_client=%r → used=%r",
              req.username,
              request.headers.get("X-Client-IP", "(not set)"),
              request.client.host if request.client else None,
              client_ip)

    row = db.execute(
        "SELECT * FROM user_tttt WHERE username = ? AND is_active = 1", (req.username,)
    ).fetchone()
    if not row or not verify_password(req.password, row["pwd_hash"]):
        rate_limit.record_failed(db, req.username)
        db.execute(
            "INSERT INTO login_logs (username, staff_id, ip_address, success, detail, created_at) VALUES (?,?,?,?,?,?)",
            (req.username, None, client_ip, 0, "Sai tên đăng nhập hoặc mật khẩu", _vn_now()),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không đúng"
        )

    staff = dict(row)
    existing_ip = get_session_ip(db, staff["id"])
    if existing_ip and existing_ip != client_ip and not req.force:
        db.execute(
            "INSERT INTO login_logs (username, staff_id, ip_address, success, detail, created_at) VALUES (?,?,?,?,?,?)",
            (req.username, staff["id"], client_ip, 0, f"Session đang hoạt động tại {existing_ip}", _vn_now()),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tài khoản đang được sử dụng tại {existing_ip}",
        )

    rate_limit.clear(db, req.username)
    session_key = str(uuid.uuid4())
    set_session(db, staff["id"], client_ip, session_key, ttl_hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    token = create_access_token({"sub": str(staff["id"]), "sk": session_key})
    db.execute(
        "INSERT INTO login_logs (username, staff_id, ip_address, success, detail, created_at) VALUES (?,?,?,?,?,?)",
        (req.username, staff["id"], client_ip, 1, None, _vn_now()),
    )
    db.commit()
    # Mật khẩu mặc định "1" → bắt buộc đổi ngay
    must_change = bool(staff.get("must_change_password", 0)) or req.password == "1"
    return Token(
        access_token=token,
        staff_id=staff["id"],
        full_name=staff["full_name"],
        role=staff["role"],
        department_id=staff.get("department_id"),
        must_change_password=must_change,
    )


@router.post("/logout")
def logout(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    clear_session(db, current["id"])
    db.commit()
    return {"message": "Đã đăng xuất"}


@router.post("/change-password")
def change_password(
    req: PasswordChange,
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    if not verify_password(req.old_password, current["pwd_hash"]):
        raise HTTPException(status_code=400, detail="Mật khẩu cũ không đúng")
    _validate_password(req.new_password)
    db.execute(
        "UPDATE user_tttt SET pwd_hash = ?, must_change_password = 0 WHERE id = ?",
        (get_password_hash(req.new_password), current["id"]),
    )
    db.commit()
    return {"message": "Đổi mật khẩu thành công"}


@router.post("/admin-reset-password")
def admin_reset_password(
    req: AdminPasswordReset,
    request: Request,
    current: dict = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    target = db.execute("SELECT * FROM user_tttt WHERE id = ?", (req.staff_id,)).fetchone()
    if not target:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    _validate_password(req.new_password)
    db.execute(
        "UPDATE user_tttt SET pwd_hash = ?, must_change_password = 1 WHERE id = ?",
        (get_password_hash(req.new_password), req.staff_id),
    )
    client_ip = request.client.host if request.client else "unknown"
    write_audit(db, current["id"], "password_reset", "staff", req.staff_id,
                f"Reset password cho {target['full_name']}", client_ip)
    db.commit()
    return {"message": f"Đã đặt lại mật khẩu cho {target['full_name']}"}


@router.get("/my-features")
def get_my_features(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    """Trả về features của user hiện tại theo nhóm.
    Admin → features=null (frontend hiểu là all-access).
    Các role khác → UNION features của tất cả nhóm user thuộc.
    """
    if current["role"] == "admin":
        return {"features": None}
    rows = db.execute("""
        SELECT DISTINCT gf.feature_code
        FROM group_members gm
        JOIN group_features gf ON gf.group_id = gm.group_id
        JOIN user_groups g ON g.id = gm.group_id AND g.is_active = 1
        WHERE gm.staff_id = ?
    """, (current["id"],)).fetchall()
    return {"features": [r["feature_code"] for r in rows]}


@router.get("/me")
def get_me(current: dict = Depends(get_current_staff)):
    return {
        "id": current["id"],
        "staff_id": current["id"],
        "employee_code": current["employee_code"],
        "full_name": current["full_name"],
        "role": current["role"],
        "username": current["username"],
        "department_id": current.get("department_id"),
        "annual_leave_days": current.get("annual_leave_days") or 12,
        "used_leave_days": current.get("used_leave_days") or 0,
    }
