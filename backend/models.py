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
    giam_doc      = "giam_doc"       # Giám đốc
    pho_giam_doc  = "pho_giam_doc"   # Phó Giám đốc
    admin         = "admin"
    hau_kiem_vien = "hau_kiem_vien"  # Hậu kiểm viên – quyền hậu kiểm
    truong_phong  = "truong_phong"   # Trưởng phòng
    pho_phong     = "pho_phong"      # Phó phòng
    chuyen_vien   = "chuyen_vien"    # Chuyên viên
    controller    = "controller"     # Deprecated – đã migrate sang pho_phong


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
    role = Column(SAEnum(RoleEnum), default=RoleEnum.chuyen_vien, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    pwd_hash = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    start_date = Column(Date, nullable=True)
    annual_leave_days = Column(Integer, default=12)   # Hạn ngạch phép năm
    used_leave_days   = Column(Integer, default=0)    # Số ngày đã dùng trong năm hiện tại
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_vn_now)

    handovers_received = relationship("Handover", back_populates="received_by_staff")
    bundles_custodian = relationship("Bundle", back_populates="custodian_staff")
    bundle_groups_created = relationship("BundleGroup", back_populates="created_by_staff")
    leave_records = relationship("LeaveRecord", foreign_keys="[LeaveRecord.staff_id]", back_populates="staff")
    delegations_as_gd  = relationship("DelegationRecord", foreign_keys="[DelegationRecord.giam_doc_id]", back_populates="giam_doc")
    delegations_as_pgd = relationship("DelegationRecord", foreign_keys="[DelegationRecord.pho_giam_doc_id]", back_populates="pho_giam_doc")


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
    borrow_reason = Column(Text, nullable=True)

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

    id              = Column(Integer, primary_key=True, index=True)
    staff_id        = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False, index=True)
    start_date      = Column(Date, nullable=False)
    end_date        = Column(Date, nullable=False)
    leave_type      = Column(SAEnum(LeaveTypeEnum), default=LeaveTypeEnum.annual)
    reason          = Column(Text, nullable=True)

    # Status: pending_ksv → pending_tong_hop → pending_gd → approved | rejected | cancelled
    status          = Column(String(20), default="pending_ksv")

    # Bước 1: KSV (Trưởng phòng hoặc Phó phòng)
    ksv_approver_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
    ksv_approved_at = Column(DateTime, nullable=True)
    ksv_comment     = Column(Text, nullable=True)

    # Bước 2: Phòng Tổng hợp
    tong_hop_approver_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
    tong_hop_approved_at = Column(DateTime, nullable=True)
    tong_hop_comment     = Column(Text, nullable=True)

    # Bước 3: Giám đốc
    gd_approver_id  = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
    gd_approved_at  = Column(DateTime, nullable=True)
    gd_comment      = Column(Text, nullable=True)

    created_at      = Column(DateTime, default=_vn_now)
    updated_at      = Column(DateTime, default=_vn_now)

    staff            = relationship("KSNBStaff", foreign_keys=[staff_id], back_populates="leave_records")
    ksv_approver     = relationship("KSNBStaff", foreign_keys=[ksv_approver_id])
    tong_hop_approver = relationship("KSNBStaff", foreign_keys=[tong_hop_approver_id])
    gd_approver      = relationship("KSNBStaff", foreign_keys=[gd_approver_id])


# ─── Ủy quyền Giám đốc ─────────────────────────────────────────────────────
class DelegationRecord(Base):
    __tablename__ = "delegation_records"

    id              = Column(Integer, primary_key=True, index=True)
    giam_doc_id     = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False, index=True)
    pho_giam_doc_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False, index=True)
    start_date      = Column(Date, nullable=False)
    end_date        = Column(Date, nullable=False)
    note            = Column(Text, nullable=True)
    created_by_id   = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=_vn_now)

    giam_doc        = relationship("KSNBStaff", foreign_keys=[giam_doc_id], back_populates="delegations_as_gd")
    pho_giam_doc    = relationship("KSNBStaff", foreign_keys=[pho_giam_doc_id], back_populates="delegations_as_pgd")
    created_by      = relationship("KSNBStaff", foreign_keys=[created_by_id])


# ─── Lịch sử thay đổi chứng từ ─────────────────────────────────────────────
class EntryChangeActionEnum(str, enum.Enum):
    handover          = "handover"           # Chuyên viên nhập mới
    edited_cv         = "edited_cv"          # Chuyên viên sửa sau khi đã confirmed
    confirmed         = "confirmed"          # HKV/KSV xác nhận đã nhận
    borrowed          = "borrowed"           # HKV/KSV xác nhận yêu cầu mượn → Đang mượn
    returned          = "returned"           # CV bàn giao lại (borrowed → pending_confirm)
    edited_hkv        = "edited_hkv"         # HKV/KSV sửa trực tiếp
    borrow_requested  = "borrow_requested"   # CV gửi yêu cầu mượn lại (confirmed → pending_confirm)
    rejected_borrow   = "rejected_borrow"    # HKV từ chối yêu cầu mượn → quay về confirmed
    rejected_return   = "rejected_return"    # HKV từ chối bàn giao lại → quay về borrowed
    rejected_handover = "rejected_handover"  # HKV từ chối chứng từ mới → xóa entry


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


# ─── Ngày lễ ────────────────────────────────────────────────────────────────
class PublicHoliday(Base):
    __tablename__ = "public_holidays"

    id   = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True)
    name = Column(String(200), nullable=False)


# ─── Nhật ký đăng nhập ──────────────────────────────────────────────────────
class LoginLog(Base):
    __tablename__ = "login_logs"

    id         = Column(Integer, primary_key=True, index=True)
    username   = Column(String(50), nullable=False, index=True)
    staff_id   = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
    ip_address = Column(String(50), nullable=True)
    success    = Column(Boolean, nullable=False)
    detail     = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_vn_now, index=True)

    staff = relationship("KSNBStaff", foreign_keys=[staff_id])


# ─── Lịch sử thao tác nghỉ phép ─────────────────────────────────────────────
class LeaveActionLog(Base):
    __tablename__ = "leave_action_logs"

    id          = Column(Integer, primary_key=True, index=True)
    leave_id    = Column(Integer, ForeignKey("leave_records.id"), nullable=False, index=True)
    actor_id    = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=False)
    # ksv_approve | ksv_reject | th_forward | th_reject | gd_approve | gd_reject | resubmit | cancel
    action      = Column(String(30), nullable=False)
    comment     = Column(Text, nullable=True)
    from_status = Column(String(20), nullable=True)
    to_status   = Column(String(20), nullable=True)
    created_at  = Column(DateTime, default=_vn_now)

    actor = relationship("KSNBStaff", foreign_keys=[actor_id])
