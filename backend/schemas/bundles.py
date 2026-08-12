from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

from .common import DepartmentOut
from .staff import StaffOut
from .handovers import DocumentEntryOut


# ─── Storage View ────────────────────────────────────────────────────────────
class StorageViewRow(BaseModel):
    days: List[int]
    bundle_ids: List[int] = []
    bundle_sheets: List[int]
    n_bundles: int

class StorageViewResponse(BaseModel):
    department_name: str
    period: str
    rows: List[StorageViewRow]
    total_sheets: int
    total_bundles: int

class StorageViewUpdateRow(BaseModel):
    bundle_ids: List[int]
    bundle_sheets: List[int]
    new_sheets: List[int] = []   # số chứng từ nhập vào ô trống → tạo tập mới

class StorageViewUpdateRequest(BaseModel):
    rows: List[StorageViewUpdateRow]


# ─── Storage Summary (toàn bộ phòng theo năm) ────────────────────────────────
class StorageSummaryDept(BaseModel):
    id: int
    name: str

class StorageSummaryCell(BaseModel):
    department_id: int
    total_sheets: int
    total_bundles: int

class StorageSummaryRow(BaseModel):
    month: int
    cells: List[StorageSummaryCell]      # cùng thứ tự với departments
    total_sheets: int
    total_bundles: int

class StorageSummaryResponse(BaseModel):
    year: int
    departments: List[StorageSummaryDept]
    rows: List[StorageSummaryRow]


# ─── Bundle ──────────────────────────────────────────────────────────────────
class BundleItemOut(BaseModel):
    id: int
    entry_id: int
    entry: Optional[DocumentEntryOut] = None
    class Config: from_attributes = True

class BundleOut(BaseModel):
    id: int
    group_id: int
    sequence: int
    total_sheets: int
    custodian_id: Optional[int]
    storage_box: Optional[str]
    storage_location: Optional[str]
    cover_printed_at: Optional[datetime]
    status: str
    items: List[BundleItemOut] = []
    class Config: from_attributes = True

class BundleGroupOut(BaseModel):
    id: int
    department_id: int
    total_bundles: int
    created_at: datetime
    notes: Optional[str]
    department: Optional[DepartmentOut] = None
    bundles: List[BundleOut] = []
    created_by_staff: Optional[StaffOut] = None
    class Config: from_attributes = True

class BundleGenerateRequest(BaseModel):
    department_id: int
    entry_ids: List[int]      # Các document entry IDs để gom
    custodian_id: Optional[int] = None
    notes: Optional[str] = None

class BundleUpdateRequest(BaseModel):
    custodian_id: Optional[int] = None
    storage_box: Optional[str] = None
    storage_location: Optional[str] = None


# ─── In bìa hồ sơ lưu trữ (mẫu M01/LHS) ──────────────────────────────────────
class ArchiveCoverRow(BaseModel):
    stt: int
    ma_vach: str
    ngay_mo: str          # "DD/MM/YYYY" — ngày đầu tiên trong tiêu đề, "" nếu không có
    tieu_de: str
    ngay_cvkt: str        # "DD/MM/YYYY"
    so_to: str

class ArchiveCoverParseResponse(BaseModel):
    rows: List[ArchiveCoverRow]
    total: int
    warnings: List[str] = []

class ArchiveCoverPrintRequest(BaseModel):
    rows: List[ArchiveCoverRow]
    as_zip: bool = False   # True = mỗi hồ sơ một file .docx trong ZIP
