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
    ADMIN          = "admin"
    HAU_KIEM_VIEN  = "hau_kiem_vien"
    TRUONG_PHONG   = "truong_phong"
    PHO_PHONG      = "pho_phong"
    CHUYEN_VIEN    = "chuyen_vien"
    GIAM_DOC       = "giam_doc"
    PHO_GIAM_DOC   = "pho_giam_doc"
