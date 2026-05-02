"""SQLAlchemy ORM Models"""
from datetime import datetime, date, timezone, timedelta

_VN_TZ = timezone(timedelta(hours=7))

def _vn_now() -> datetime:
    """Thời gian hiện tại theo múi giờ Hà Nội (UTC+7), lưu dạng naive."""
    return datetime.now(_VN_TZ).replace(tzinfo=None)
from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime,
    ForeignKey, Text, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import relationship
from backend.database import Base
import enum


class RoleEnum(str, enum.Enum):
    admin = "admin"
    hau_kiem_vien = "hau_kiem_vien"  # Hậu kiểm viên – như admin, trừ quản lý nhân sự
    controller = "controller"        # Kiểm soát viên
    viewer = "viewer"
    chuyen_vien = "chuyen_vien"      # Chuyên viên – chỉ thao tác bàn giao chứng từ


class LeaveTypeEnum(str, enum.Enum):
    annual = "annual"       # Nghỉ phép năm
    sick = "sick"           # Nghỉ ốm
    personal = "personal"   # Nghỉ việc riêng
    other = "other"         # Khác


# ─── Phòng (Departments) ────────────────────────────────────────────────────
class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False)  # NOSTRO, SWIFT, PAYMENT, ACCOUNTING
    name = Column(String(200), nullable=False)
    is_source = Column(Boolean, default=True)  # True = phòng nguồn giao chứng từ
    is_active = Column(Boolean, default=True)

    source_users = relationship("SourceUser", back_populates="department")
    handovers = relationship("Handover", back_populates="department")
    bundle_groups = relationship("BundleGroup", back_populates="department")


# ─── Cán bộ KSNB ────────────────────────────────────────────────────────────
class KSNBStaff(Base):
    __tablename__ = "ksnb_staff"

    id = Column(Integer, primary_key=True, index=True)
    employee_code = Column(String(20), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(SAEnum(RoleEnum), default=RoleEnum.viewer, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    pwd_hash = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    start_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_vn_now)

    handovers_received = relationship("Handover", back_populates="received_by_staff")
    bundles_custodian = relationship("Bundle", back_populates="custodian_staff")
    bundle_groups_created = relationship("BundleGroup", back_populates="created_by_staff")
    leave_records = relationship("LeaveRecord", foreign_keys="[LeaveRecord.staff_id]", back_populates="staff")


# ─── User tại phòng nguồn ───────────────────────────────────────────────────
class SourceUser(Base):
    __tablename__ = "source_users"

    id = Column(Integer, primary_key=True, index=True)
    user_code = Column(String(50), nullable=False)    # User IPCAS, e.g. HQBQTRUNG
    full_name = Column(String(100), nullable=True)    # User PaymentHub, e.g. Trungbuiquang
    vn_name   = Column(String(200), nullable=True)    # Họ và tên thực, e.g. Bùi Quang Trung
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)

    department = relationship("Department", back_populates="source_users")
    document_entries = relationship("DocumentEntry", back_populates="source_user")


# ─── Phiếu bàn giao ─────────────────────────────────────────────────────────
class Handover(Base):
    __tablename__ = "handovers"
    __table_args__ = (UniqueConstraint("department_id", "handover_date", name="uq_handover_dept_date"),)

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False, index=True)
    handover_date = Column(Date, nullable=False)        # Ngày bàn giao thực tế
    received_by_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True, index=True)
    delivered_by = Column(String(100), nullable=True)   # Tên người giao
    notes = Column(Text, nullable=True)
    status = Column(String(20), default="draft")        # draft, confirmed
    created_at = Column(DateTime, default=_vn_now)

    department = relationship("Department", back_populates="handovers")
    received_by_staff = relationship("KSNBStaff", back_populates="handovers_received")
    entries = relationship("DocumentEntry", back_populates="handover", cascade="all, delete-orphan")


# ─── Chi tiết chứng từ ──────────────────────────────────────────────────────
class DocumentEntry(Base):
    __tablename__ = "document_entries"
    __table_args__ = (UniqueConstraint("handover_id", "source_user_id", "transaction_date", name="uq_entry_handover_user_date"),)

    id = Column(Integer, primary_key=True, index=True)
    handover_id = Column(Integer, ForeignKey("handovers.id"), nullable=False, index=True)
    source_user_id = Column(Integer, ForeignKey("source_users.id"), nullable=False, index=True)
    transaction_date = Column(Date, nullable=False, index=True)     # Ngày giao dịch chứng từ
    sheet_count = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)
    entry_status = Column(String(20), default="confirmed")          # pending_confirm | confirmed | borrowed
    entered_by_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
    confirmed_by_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    borrowed_at = Column(DateTime, nullable=True)

    handover = relationship("Handover", back_populates="entries")
    source_user = relationship("SourceUser", back_populates="document_entries")
    bundle_items = relationship("BundleItem", back_populates="entry")
    change_logs = relationship("EntryChangeLog", back_populates="entry", cascade="all, delete-orphan")


# ─── Nhóm tập ───────────────────────────────────────────────────────────────
class BundleGroup(Base):
    __tablename__ = "bundle_groups"

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False, index=True)
    total_bundles = Column(Integer, default=1)
    created_by_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=_vn_now)
    notes = Column(Text, nullable=True)

    department = relationship("Department", back_populates="bundle_groups")
    created_by_staff = relationship("KSNBStaff", back_populates="bundle_groups_created")
    bundles = relationship("Bundle", back_populates="group", cascade="all, delete-orphan")


# ─── Tập chứng từ ───────────────────────────────────────────────────────────
class Bundle(Base):
    __tablename__ = "bundles"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("bundle_groups.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)           # 1, 2, 3... (thứ tự trong nhóm)
    total_sheets = Column(Integer, default=0)
    custodian_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True, index=True)
    storage_box = Column(String(50), nullable=True)      # Số hộp
    storage_location = Column(String(200), nullable=True) # Vị trí kệ
    cover_printed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")       # pending, printed, stored
    cover_units = Column(Text, nullable=True)            # JSON — dữ liệu hiển thị bìa (user_code/full_name/date/sheet_count)

    group = relationship("BundleGroup", back_populates="bundles")
    custodian_staff = relationship("KSNBStaff", back_populates="bundles_custodian")
    items = relationship("BundleItem", back_populates="bundle", cascade="all, delete-orphan")


# ─── Chi tiết tập ───────────────────────────────────────────────────────────
class BundleItem(Base):
    __tablename__ = "bundle_items"

    id = Column(Integer, primary_key=True, index=True)
    bundle_id = Column(Integer, ForeignKey("bundles.id"), nullable=False, index=True)
    entry_id = Column(Integer, ForeignKey("document_entries.id"), nullable=False, index=True)

    bundle = relationship("Bundle", back_populates="items")
    entry = relationship("DocumentEntry", back_populates="bundle_items")


# ─── Nghỉ phép ──────────────────────────────────────────────────────────────
class LeaveRecord(Base):
    __tablename__ = "leave_records"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    leave_type = Column(SAEnum(LeaveTypeEnum), default=LeaveTypeEnum.annual)
    reason = Column(Text, nullable=True)
    status = Column(String(20), default="pending")  # pending, approved, rejected
    approved_by_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
    created_at = Column(DateTime, default=_vn_now)

    staff = relationship("KSNBStaff", foreign_keys=[staff_id], back_populates="leave_records")


# ─── Lịch sử thay đổi chứng từ ─────────────────────────────────────────────
class EntryChangeActionEnum(str, enum.Enum):
    handover   = "handover"    # Chuyên viên nhập mới
    edited_cv  = "edited_cv"   # Chuyên viên sửa sau khi đã confirmed
    confirmed  = "confirmed"   # HKV/KSV xác nhận đã nhận
    borrowed   = "borrowed"    # Chuyên viên mượn lại
    returned   = "returned"    # HKV/KSV xác nhận đã trả
    edited_hkv = "edited_hkv"  # HKV/KSV sửa trực tiếp


class EntryChangeLog(Base):
    __tablename__ = "entry_change_logs"

    id              = Column(Integer, primary_key=True, index=True)
    entry_id        = Column(Integer, ForeignKey("document_entries.id"), nullable=False, index=True)
    action          = Column(SAEnum(EntryChangeActionEnum), nullable=False)
    performed_by_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False, index=True)
    timestamp       = Column(DateTime, default=_vn_now)
    old_sheet_count = Column(Integer, nullable=True)
    new_sheet_count = Column(Integer, nullable=True)
    notes           = Column(Text, nullable=True)

    entry        = relationship("DocumentEntry", back_populates="change_logs")
    performed_by = relationship("KSNBStaff")
