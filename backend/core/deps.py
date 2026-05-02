"""FastAPI dependency injection"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.core.security import decode_token
from backend.core.sessions import get_session_ip
from backend.models import KSNBStaff

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_staff(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> KSNBStaff:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ")
    staff_id = payload.get("sub")
    if not staff_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ")
    staff = db.query(KSNBStaff).filter(KSNBStaff.id == int(staff_id), KSNBStaff.is_active == True).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản không tồn tại")
    if get_session_ip(staff.id) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên đăng nhập đã hết hạn hoặc đã đăng xuất")
    return staff


def require_admin(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Chỉ Quản trị viên (dùng cho quản lý nhân sự, đổi mật khẩu người khác)."""
    if current.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Admin")
    return current


def require_hkv_or_above(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Hậu kiểm viên hoặc Quản trị viên (mọi quyền admin trừ quản lý nhân sự)."""
    if current.role not in ("admin", "hau_kiem_vien"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Hậu kiểm viên trở lên")
    return current


def require_controller(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    if current.role not in ("admin", "hau_kiem_vien", "controller"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Controller trở lên")
    return current


def require_handover_write(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Chuyen vien, controller, hau_kiem_vien, admin đều được nhập/sửa bàn giao."""
    if current.role not in ("admin", "hau_kiem_vien", "controller", "chuyen_vien"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền thao tác bàn giao chứng từ")
    return current


def require_ksnb(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Chỉ KSNB staff (không phải GDV) mới được truy cập."""
    if str(current.role) == "chuyen_vien":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền truy cập tính năng này")
    return current
