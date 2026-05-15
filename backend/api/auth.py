"""Authentication endpoints"""
import re
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import KSNBStaff, LoginLog, _vn_now
from backend.schemas import LoginRequest, Token, PasswordChange, AdminPasswordReset
from backend.core.security import verify_password, create_access_token, get_password_hash
from backend.core.deps import get_current_staff, require_admin
from backend.core.sessions import set_session, get_session_ip, clear_session
from backend.core.config import settings
from backend.core import rate_limit

router = APIRouter(prefix="/api/auth", tags=["Auth"])

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
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # ── Rate limit ──
    wait = rate_limit.seconds_locked(req.username)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Quá nhiều lần đăng nhập sai. Thử lại sau {wait} giây.",
        )

    client_ip = (
        request.headers.get("X-Client-IP")
        or (request.client.host if request.client else "unknown")
    )

    staff = db.query(KSNBStaff).filter(
        KSNBStaff.username == req.username,
        KSNBStaff.is_active == True
    ).first()
    if not staff or not verify_password(req.password, staff.pwd_hash):
        rate_limit.record_failed(req.username)
        db.add(LoginLog(
            username=req.username, staff_id=None, ip_address=client_ip,
            success=False, detail="Sai tên đăng nhập hoặc mật khẩu", created_at=_vn_now(),
        ))
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không đúng"
        )

    existing_ip = get_session_ip(staff.id)
    if existing_ip and existing_ip != client_ip and not req.force:
        db.add(LoginLog(
            username=req.username, staff_id=staff.id, ip_address=client_ip,
            success=False, detail=f"Session đang hoạt động tại {existing_ip}", created_at=_vn_now(),
        ))
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tài khoản đang được sử dụng tại {existing_ip}",
        )

    rate_limit.clear(req.username)
    set_session(staff.id, client_ip, ttl_hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    token = create_access_token({"sub": str(staff.id)})
    db.add(LoginLog(
        username=req.username, staff_id=staff.id, ip_address=client_ip,
        success=True, detail=None, created_at=_vn_now(),
    ))
    db.commit()
    return Token(
        access_token=token,
        staff_id=staff.id,
        full_name=staff.full_name,
        role=staff.role,
        department_id=staff.department_id,
        must_change_password=bool(staff.must_change_password),
    )


@router.post("/logout")
def logout(current: KSNBStaff = Depends(get_current_staff)):
    clear_session(current.id)
    return {"message": "Đã đăng xuất"}


@router.post("/change-password")
def change_password(
    req: PasswordChange,
    current: KSNBStaff = Depends(get_current_staff),
    db: Session = Depends(get_db)
):
    if not verify_password(req.old_password, current.pwd_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu cũ không đúng")
    _validate_password(req.new_password)
    current.pwd_hash = get_password_hash(req.new_password)
    current.must_change_password = False
    db.commit()
    return {"message": "Đổi mật khẩu thành công"}


@router.post("/admin-reset-password")
def admin_reset_password(
    req: AdminPasswordReset,
    current: KSNBStaff = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Admin đặt lại mật khẩu cho user khác (không cần nhập mật khẩu cũ)."""
    target = db.query(KSNBStaff).filter(KSNBStaff.id == req.staff_id).first()
    if not target:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    _validate_password(req.new_password)
    target.pwd_hash = get_password_hash(req.new_password)
    target.must_change_password = True
    db.commit()
    return {"message": f"Đã đặt lại mật khẩu cho {target.full_name}"}


@router.get("/me")
def get_me(current: KSNBStaff = Depends(get_current_staff)):
    return {
        "id": current.id,
        "staff_id": current.id,
        "employee_code": current.employee_code,
        "full_name": current.full_name,
        "role": current.role,
        "username": current.username,
        "department_id": current.department_id,
        "annual_leave_days": current.annual_leave_days or 12,
        "used_leave_days": current.used_leave_days or 0,
    }
