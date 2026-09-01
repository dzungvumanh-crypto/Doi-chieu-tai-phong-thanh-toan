from enum import Enum


class EntryStatus(str, Enum):
    PENDING   = "pending_confirm"
    CONFIRMED = "confirmed"
    BORROWED  = "borrowed"
    REJECTED  = "rejected"


class LeaveStatus(str, Enum):
    PENDING_KSV      = "pending_ksv"
    PENDING_TONG_HOP = "pending_tong_hop"
    PENDING_GD       = "pending_gd"
    APPROVED         = "approved"
    REJECTED         = "rejected"
    CANCELLED        = "cancelled"


class StaffRole(str, Enum):
    ADMIN          = "admin"        # Quản trị viên cấp 1 — toàn quyền
    ADMIN_L2       = "admin_l2"     # Quản trị viên cấp 2 — quyền theo nhóm
    HAU_KIEM_VIEN  = "hau_kiem_vien"
    TRUONG_PHONG   = "truong_phong"
    PHO_PHONG      = "pho_phong"
    CHUYEN_VIEN    = "chuyen_vien"
    GIAM_DOC       = "giam_doc"
    PHO_GIAM_DOC   = "pho_giam_doc"


# Bậc quyền — số lớn hơn = quyền cao hơn. Chép từ thứ tự đã ghi trong
# docs/DESIGN.md ("Role Hierarchy"), không phải quy ước mới:
#   admin > hau_kiem_vien > giam_doc / pho_giam_doc > truong_phong > pho_phong > chuyen_vien
# GĐ và PGĐ cùng bậc: PGĐ chỉ khác ở chỗ cần uỷ quyền mới duyệt được bước GĐ.
# Dùng để chặn leo thang quyền khi gán vai trò — xem `_chan_leo_thang_quyen()`
# trong backend/api/staff.py.
ROLE_RANK = {
    StaffRole.ADMIN.value:         100,
    StaffRole.ADMIN_L2.value:       90,
    StaffRole.HAU_KIEM_VIEN.value:  70,
    StaffRole.GIAM_DOC.value:       60,
    StaffRole.PHO_GIAM_DOC.value:   60,
    StaffRole.TRUONG_PHONG.value:   40,
    StaffRole.PHO_PHONG.value:      30,
    StaffRole.CHUYEN_VIEN.value:    10,
}

VALID_ROLES = frozenset(r.value for r in StaffRole)
