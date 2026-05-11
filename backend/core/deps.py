"""FastAPI dependency injection"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.core.security import decode_token
from backend.core.sessions import get_session_ip
from backend.models import KSNBStaff, Department

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Mã phòng Tổng hợp — dùng chung để kiểm tra quyền
TONG_HOP_CODES = frozenset(("TONGHOP", "TONG_HOP", "TH"))


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
    """Deprecated alias — dùng require_pho_phong_or_above."""
    return require_pho_phong_or_above(current)


def require_pho_phong_or_above(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Phó phòng, Trưởng phòng, Hậu kiểm viên, hoặc Admin."""
    if current.role not in ("admin", "hau_kiem_vien", "truong_phong", "pho_phong"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Phó phòng trở lên")
    return current


def require_handover_write(
    current: KSNBStaff = Depends(get_current_staff),
    db: Session = Depends(get_db),
) -> KSNBStaff:
    """Chuyên viên, Phó phòng, Trưởng phòng, Hậu kiểm viên, Admin đều được nhập/sửa bàn giao.
    Ngoại lệ: staff thuộc phòng Tổng hợp bị chặn."""
    if current.role not in ("admin", "hau_kiem_vien", "truong_phong", "pho_phong", "chuyen_vien"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền thao tác bàn giao chứng từ")
    if current.role in ("chuyen_vien", "pho_phong", "truong_phong") and current.department_id:
        dept = db.query(Department).filter(Department.id == current.department_id).first()
        if dept and dept.code.upper() in TONG_HOP_CODES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Phòng Tổng hợp không có quyền truy cập bàn giao chứng từ")
    return current


def require_ksnb(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Chỉ KSNB staff (không phải Chuyên viên/GDV) mới được truy cập."""
    if current.role == "chuyen_vien":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền truy cập tính năng này")
    return current


def require_ksv(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Phê duyệt bước KSV: Trưởng phòng, Phó phòng."""
    if current.role not in ("truong_phong", "pho_phong"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Trưởng phòng hoặc Phó phòng")
    return current


def require_gd_level(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Phê duyệt bước GĐ: Giám đốc, Phó Giám đốc. Kiểm tra ủy quyền tại endpoint."""
    if current.role not in ("giam_doc", "pho_giam_doc"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Giám đốc")
    return current


def require_admin_or_gd(current: KSNBStaff = Depends(get_current_staff)) -> KSNBStaff:
    """Xem nhật ký hệ thống: Admin, Giám đốc, Phó Giám đốc."""
    if current.role not in ("admin", "giam_doc", "pho_giam_doc"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Admin hoặc Giám đốc")
    return current
