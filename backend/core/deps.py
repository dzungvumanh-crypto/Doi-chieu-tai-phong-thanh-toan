"""FastAPI dependency injection — raw SQL."""
import sqlite3
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from backend.core.enums import StaffRole
from backend.database import get_db, compute_annual_leave
from backend.core.security import decode_token
from backend.core.sessions import get_session_ip, get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Mã phòng Tổng hợp — dùng chung để kiểm tra quyền
TONG_HOP_CODES = frozenset(("TONGHOP", "TONG_HOP", "TH"))

# Đường duy nhất còn đi được khi tài khoản đang bị bắt đổi mật khẩu.
# Trước đây cờ `must_change_password` chỉ được frontend dùng để chuyển trang:
# backend vẫn cấp token đầy đủ quyền, nên ai đăng nhập bằng mật khẩu mặc định
# rồi gọi thẳng API (hoặc chỉ cần gõ /home lên thanh địa chỉ) là dùng hệ thống
# bình thường, không bao giờ phải đổi. Chặn ở đây thì cái cửa đó đóng lại.
#
# Bốn đường này phải mở, nếu không chính màn hình đổi mật khẩu cũng không chạy:
#   me / my-features — layout và nhịp kiểm tra phiên 60 giây gọi liên tục
#   change-password  — việc cần làm
#   logout           — phải cho người ta thoát ra được
_DUONG_MO_KHI_BAT_DOI_MK = frozenset((
    "/api/auth/change-password",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/my-features",
))


def get_current_staff(
    request: Request,
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
    session_row = get_session(db, int(staff_id))
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã hết hạn hoặc đã đăng xuất",
        )
    # Nếu session_key trong JWT không khớp DB → phiên này đã bị thay thế bởi đăng nhập mới
    token_sk = payload.get("sk")
    stored_sk = session_row["session_key"] if session_row else None
    if token_sk and stored_sk and token_sk != stored_sk:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="__session_displaced__",
        )
    staff = dict(row)
    if staff.get("must_change_password") and request.url.path not in _DUONG_MO_KHI_BAT_DOI_MK:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="__must_change_password__",
        )
    # Tính annual_leave_days từ join_industry_date nếu có (ghi đè giá trị lưu sẵn)
    if staff.get("join_industry_date"):
        staff["annual_leave_days"] = compute_annual_leave(staff["join_industry_date"])
    return staff


def require_admin(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] != StaffRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Admin")
    return current


# Quản trị viên cấp 1 + cấp 2. Dùng cho màn quản trị mà cấp 2 cũng được vào
# (Phân quyền chức năng). KHÔNG dùng thay `require_admin` ở chỗ khác: cấp 2
# vốn là "quyền theo nhóm", mở rộng đại trà sẽ xoá luôn ranh giới hai cấp.
_ROLES_QUAN_TRI = frozenset((StaffRole.ADMIN.value, StaffRole.ADMIN_L2.value))


def require_admin_any(current: dict = Depends(get_current_staff)) -> dict:
    if current["role"] not in _ROLES_QUAN_TRI:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cần quyền Quản trị viên")
    return current


def require_feature(feature_code: str):
    """Dependency factory — cho phép admin hoặc user có feature_code qua group."""
    def _check(
        current: dict = Depends(get_current_staff),
        db: sqlite3.Connection = Depends(get_db),
    ) -> dict:
        if current["role"] == StaffRole.ADMIN:
            return current
        row = db.execute(
            """SELECT 1 FROM group_features gf
               JOIN group_members gm ON gm.group_id = gf.group_id
               JOIN user_groups g ON g.id = gm.group_id AND g.is_active = 1
               WHERE gm.staff_id = ? AND gf.feature_code = ?
               LIMIT 1""",
            (current["id"], feature_code),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Không có quyền truy cập tính năng này",
            )
        return current
    return _check


def require_any_feature(*feature_codes: str):
    """Như require_feature(), nhưng cho qua nếu current có ÍT NHẤT MỘT trong các
    feature_code — dùng cho endpoint dùng chung nhiều module (VD folder-picker
    /api/fs/browse dùng chung cho ACH/ILO1000/459901/Đối chiếu Song phương),
    nơi require_feature() với đúng 1 mã sẽ chặn nhầm user chỉ có menu module khác."""
    def _check(
        current: dict = Depends(get_current_staff),
        db: sqlite3.Connection = Depends(get_db),
    ) -> dict:
        if current["role"] == StaffRole.ADMIN:
            return current
        placeholders = ",".join("?" * len(feature_codes))
        row = db.execute(
            f"""SELECT 1 FROM group_features gf
               JOIN group_members gm ON gm.group_id = gf.group_id
               JOIN user_groups g ON g.id = gm.group_id AND g.is_active = 1
               WHERE gm.staff_id = ? AND gf.feature_code IN ({placeholders})
               LIMIT 1""",
            (current["id"], *feature_codes),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không có quyền truy cập tính năng này",
            )
        return current
    return _check
