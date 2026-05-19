"""FastAPI dependency injection — raw SQL."""
import sqlite3
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.core.security import decode_token
from backend.core.sessions import get_session_ip

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Mã phòng Tổng hợp — dùng chung để kiểm tra quyền
TONG_HOP_CODES = frozenset(("TONGHOP", "TONG_HOP", "TH"))


def get_current_staff(
    token: str = Depends(oauth2_scheme),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ")
    staff_id = payload.get("sub")
    if not staff_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ")
    row = db.execute(
        "SELECT * FROM user_tttt WHERE id = ? AND is_active = 1", (int(staff_id),)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản không tồn tại")
    if get_session_ip(db, int(staff_id)) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã hết hạn hoặc đã đăng xuất",
        )
    return dict(row)


def require_admin(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] != StaffRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Admin")
    return current


def require_hkv_or_above(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] not in (StaffRole.ADMIN, StaffRole.HAU_KIEM_VIEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Hậu kiểm viên trở lên")
    return current


def require_controller(current: dict = Depends(get_current_staff)) -> dict:
    """Deprecated alias — dùng require_pho_phong_or_above."""
    return require_pho_phong_or_above(current)


def require_pho_phong_or_above(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] not in (StaffRole.ADMIN, StaffRole.HAU_KIEM_VIEN, StaffRole.TRUONG_PHONG, StaffRole.PHO_PHONG):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Phó phòng trở lên")
    return current


def require_handover_write(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Chuyên viên, Phó phòng, Trưởng phòng, Hậu kiểm viên, Admin đều được nhập/sửa bàn giao.
    Ngoại lệ: staff thuộc phòng Tổng hợp bị chặn."""
    if current["role"] not in (StaffRole.ADMIN, StaffRole.HAU_KIEM_VIEN, StaffRole.TRUONG_PHONG, StaffRole.PHO_PHONG, StaffRole.CHUYEN_VIEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền thao tác bàn giao chứng từ")
    dept_id = current.get("department_id")
    if current["role"] in (StaffRole.CHUYEN_VIEN, StaffRole.PHO_PHONG, StaffRole.TRUONG_PHONG) and dept_id:
        row = db.execute("SELECT code FROM departments WHERE id = ?", (dept_id,)).fetchone()
        if row and row["code"].upper() in TONG_HOP_CODES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Phòng Tổng hợp không có quyền truy cập bàn giao chứng từ")
    return current


def require_ksnb(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] == StaffRole.CHUYEN_VIEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền truy cập tính năng này")
    return current


def require_ksv(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] not in (StaffRole.TRUONG_PHONG, StaffRole.PHO_PHONG):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Trưởng phòng hoặc Phó phòng")
    return current


def require_gd_level(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] not in (StaffRole.GIAM_DOC, StaffRole.PHO_GIAM_DOC):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Giám đốc")
    return current


def require_admin_or_gd(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] not in (StaffRole.ADMIN, StaffRole.GIAM_DOC, StaffRole.PHO_GIAM_DOC):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Admin hoặc Giám đốc")
    return current
