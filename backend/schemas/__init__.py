# Re-export tất cả schemas — backward compat với `from backend.schemas import X`
# Trong code mới, import trực tiếp từ file domain: from backend.schemas.leaves import LeaveCreate
from .auth import LoginRequest, Token, PasswordChange, AdminPasswordReset
from .common import DepartmentOut
from .staff import StaffCreate, StaffUpdate, StaffOut
from .handovers import (
    DocumentEntryIn, DocumentEntryOut,
    HandoverCreate, HandoverOut,
    GridEntryOut, GridResponse,
    EntryUpsertRequest, BorrowRequest, HandbackRequest, RejectRequest,
    EntryHistoryItem, EntryHistoryOut,
    ArchiveRecord, HandoverArchiveResponse,
)
from .bundles import (
    StorageViewRow, StorageViewResponse, StorageViewUpdateRow, StorageViewUpdateRequest,
    BundleItemOut, BundleOut, BundleGroupOut,
    BundleGenerateRequest, BundleUpdateRequest,
)
from .leaves import (
    LeaveCreate, LeaveReview, TongHopReview,
    LeaveOut, LeaveActionLogOut,
    DelegationCreate, DelegationOut,
)

__all__ = [
    "LoginRequest", "Token", "PasswordChange", "AdminPasswordReset",
    "DepartmentOut",
    "StaffCreate", "StaffUpdate", "StaffOut",
    "DocumentEntryIn", "DocumentEntryOut",
    "HandoverCreate", "HandoverOut",
    "GridEntryOut", "GridResponse",
    "EntryUpsertRequest", "BorrowRequest", "HandbackRequest", "RejectRequest",
    "EntryHistoryItem", "EntryHistoryOut",
    "ArchiveRecord", "HandoverArchiveResponse",
    "StorageViewRow", "StorageViewResponse", "StorageViewUpdateRow", "StorageViewUpdateRequest",
    "BundleItemOut", "BundleOut", "BundleGroupOut",
    "BundleGenerateRequest", "BundleUpdateRequest",
    "LeaveCreate", "LeaveReview", "TongHopReview",
    "LeaveOut", "LeaveActionLogOut",
    "DelegationCreate", "DelegationOut",
]
