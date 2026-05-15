"""FastAPI Application Entry Point"""
import logging
import logging.handlers
import os
import sqlite3
import sys

# Thêm root vào path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


# ── Logging tập trung ──────────────────────────────────────────────────────────
def _setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    if root.handlers:       # Tránh duplicate khi uvicorn --reload
        return
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = logging.handlers.RotatingFileHandler(
        "logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

_setup_logging()
from backend.api.auth import router as auth_router
from backend.api.staff import router as staff_router
from backend.api.departments import dept_router
from backend.api.handovers import router as handover_router
from backend.api.bundles import router as bundle_router
from backend.api.leaves import router as leaves_router
from backend.api.delegations import router as delegations_router
from backend.api.logs import router as logs_router
from backend.api.dashboard import router as dashboard_router
from backend.api.holidays import router as holidays_router
from backend.api.reports import router as reports_router
from backend.database import DB_PATH


# ── Tạo tables (fresh install) ────────────────────────────────────────────────
def _create_tables(db_path: str):
    """Tạo tất cả bảng nếu chưa có — idempotent."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")
    statements = [
        """CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(20) NOT NULL UNIQUE,
            name VARCHAR(200) NOT NULL,
            is_source BOOLEAN DEFAULT 1,
            is_active BOOLEAN DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS ksnb_staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_code VARCHAR(20) NOT NULL UNIQUE,
            full_name VARCHAR(100) NOT NULL,
            role TEXT NOT NULL DEFAULT 'chuyen_vien',
            department_id INTEGER REFERENCES departments(id),
            username VARCHAR(50) NOT NULL UNIQUE,
            pwd_hash VARCHAR(200) NOT NULL,
            phone VARCHAR(20),
            email VARCHAR(100),
            start_date DATE,
            annual_leave_days INTEGER DEFAULT 12,
            used_leave_days INTEGER DEFAULT 0,
            must_change_password BOOLEAN DEFAULT 0,
            ipcas_code VARCHAR(20),
            payment_username VARCHAR(50),
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS source_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_code TEXT,
            full_name TEXT,
            department_id INTEGER REFERENCES departments(id),
            is_active INTEGER DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS handovers (
            id INTEGER NOT NULL PRIMARY KEY,
            department_id INTEGER NOT NULL REFERENCES departments(id),
            handover_date DATE NOT NULL,
            received_by_id INTEGER REFERENCES ksnb_staff(id),
            delivered_by VARCHAR(100),
            notes TEXT,
            status VARCHAR(20) DEFAULT 'draft',
            created_at DATETIME,
            UNIQUE(department_id, handover_date)
        )""",
        """CREATE TABLE IF NOT EXISTS document_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            handover_id INTEGER NOT NULL REFERENCES handovers(id),
            source_user_id INTEGER,
            transaction_date DATE NOT NULL,
            sheet_count INTEGER NOT NULL,
            notes TEXT,
            entry_status TEXT DEFAULT 'confirmed',
            entered_by_id INTEGER REFERENCES ksnb_staff(id),
            confirmed_by_id INTEGER REFERENCES ksnb_staff(id),
            confirmed_at DATETIME,
            borrowed_at DATETIME,
            borrow_reason TEXT,
            staff_id INTEGER REFERENCES ksnb_staff(id)
        )""",
        """CREATE TABLE IF NOT EXISTS bundle_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL REFERENCES departments(id),
            total_bundles INTEGER DEFAULT 1,
            created_by_id INTEGER NOT NULL REFERENCES ksnb_staff(id),
            created_at DATETIME,
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES bundle_groups(id),
            sequence INTEGER NOT NULL,
            total_sheets INTEGER DEFAULT 0,
            custodian_id INTEGER REFERENCES ksnb_staff(id),
            storage_box VARCHAR(50),
            storage_location VARCHAR(200),
            cover_printed_at DATETIME,
            status VARCHAR(20) DEFAULT 'pending',
            cover_units TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS bundle_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_id INTEGER NOT NULL REFERENCES bundles(id),
            entry_id INTEGER NOT NULL REFERENCES document_entries(id)
        )""",
        """CREATE TABLE IF NOT EXISTS entry_change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL REFERENCES document_entries(id),
            action TEXT NOT NULL,
            performed_by_id INTEGER NOT NULL REFERENCES ksnb_staff(id),
            timestamp DATETIME,
            old_sheet_count INTEGER,
            new_sheet_count INTEGER,
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES ksnb_staff(id),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            leave_type TEXT DEFAULT 'annual',
            reason TEXT,
            status TEXT DEFAULT 'pending_ksv',
            ksv_approver_id INTEGER REFERENCES ksnb_staff(id),
            ksv_approved_at DATETIME,
            ksv_comment TEXT,
            tong_hop_approver_id INTEGER REFERENCES ksnb_staff(id),
            tong_hop_approved_at DATETIME,
            tong_hop_comment TEXT,
            gd_approver_id INTEGER REFERENCES ksnb_staff(id),
            gd_approved_at DATETIME,
            gd_comment TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )""",
    ]
    for s in statements:
        cur.execute(s)
    cur.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()


_create_tables(DB_PATH)


def _ensure_indexes():
    """Tạo index và migrate schema trên DB hiện tại (idempotent)."""
    schema_migrations = [
        # Schema migration – thêm cột mới nếu chưa có (SQLite không hỗ trợ IF NOT EXISTS cho ADD COLUMN)
        # Bọc trong try/except ở Python để bỏ qua lỗi "duplicate column"
        "ALTER TABLE bundles ADD COLUMN cover_units TEXT",
        # Cột mới cho KSNBStaff (chuyên viên)
        "ALTER TABLE ksnb_staff ADD COLUMN department_id INTEGER REFERENCES departments(id)",
        # Cột mới cho DocumentEntry
        "ALTER TABLE document_entries ADD COLUMN entry_status TEXT DEFAULT 'confirmed'",
        "ALTER TABLE document_entries ADD COLUMN entered_by_id INTEGER REFERENCES ksnb_staff(id)",
        "ALTER TABLE document_entries ADD COLUMN confirmed_by_id INTEGER REFERENCES ksnb_staff(id)",
        "ALTER TABLE document_entries ADD COLUMN confirmed_at DATETIME",
        "ALTER TABLE document_entries ADD COLUMN borrowed_at DATETIME",
        "ALTER TABLE document_entries ADD COLUMN borrow_reason TEXT",
        # Gán phòng KSNB cho staff cũ không có department_id (idempotent)
        "UPDATE ksnb_staff SET department_id = (SELECT id FROM departments WHERE code = 'KSNB' LIMIT 1) WHERE department_id IS NULL AND role IN ('admin', 'hau_kiem_vien', 'controller', 'viewer')",
        # Quyền mới — migrate controller → pho_phong
        "ALTER TABLE ksnb_staff ADD COLUMN annual_leave_days INTEGER DEFAULT 12",
        "ALTER TABLE ksnb_staff ADD COLUMN used_leave_days INTEGER DEFAULT 0",
        "UPDATE ksnb_staff SET role = 'pho_phong' WHERE role = 'controller'",
        "UPDATE ksnb_staff SET role = 'chuyen_vien' WHERE role = 'viewer'",
        "INSERT OR IGNORE INTO departments (code, name, is_source, is_active) VALUES ('TH', 'Phòng Tổng hợp', 0, 1)",
        "INSERT OR IGNORE INTO departments (code, name, is_source, is_active) VALUES ('BGD', 'Ban Giám đốc', 0, 1)",
        # Gán GĐ/PGĐ vào Ban Giám đốc (idempotent — chạy lại không hại)
        "UPDATE ksnb_staff SET department_id = (SELECT id FROM departments WHERE code = 'BGD' LIMIT 1) WHERE role IN ('giam_doc', 'pho_giam_doc')",
        # Mở rộng LeaveRecord cho workflow 2 bước
        "ALTER TABLE leave_records ADD COLUMN ksv_approver_id INTEGER REFERENCES ksnb_staff(id)",
        "ALTER TABLE leave_records ADD COLUMN ksv_approved_at DATETIME",
        "ALTER TABLE leave_records ADD COLUMN ksv_comment TEXT",
        "ALTER TABLE leave_records ADD COLUMN gd_approver_id INTEGER REFERENCES ksnb_staff(id)",
        "ALTER TABLE leave_records ADD COLUMN gd_approved_at DATETIME",
        "ALTER TABLE leave_records ADD COLUMN gd_comment TEXT",
        "ALTER TABLE leave_records ADD COLUMN updated_at DATETIME",
        "UPDATE leave_records SET status = 'pending_ksv' WHERE status = 'pending'",
        # Bảng ủy quyền GĐ
        """CREATE TABLE IF NOT EXISTS delegation_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giam_doc_id INTEGER NOT NULL REFERENCES ksnb_staff(id),
            pho_giam_doc_id INTEGER NOT NULL REFERENCES ksnb_staff(id),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            note TEXT,
            created_by_id INTEGER NOT NULL REFERENCES ksnb_staff(id),
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME
        )""",
        # Workflow nghỉ phép 3 bước — Phòng Tổng hợp
        "ALTER TABLE leave_records ADD COLUMN tong_hop_approver_id INTEGER REFERENCES ksnb_staff(id)",
        "ALTER TABLE leave_records ADD COLUMN tong_hop_approved_at DATETIME",
        "ALTER TABLE leave_records ADD COLUMN tong_hop_comment TEXT",
        # Bảng ngày lễ
        """CREATE TABLE IF NOT EXISTS public_holidays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL UNIQUE,
            name TEXT NOT NULL
        )""",
        # Bảng nhật ký đăng nhập
        """CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            staff_id INTEGER REFERENCES ksnb_staff(id),
            ip_address TEXT,
            success INTEGER NOT NULL,
            detail TEXT,
            created_at DATETIME
        )""",
        # Bảng lịch sử thao tác nghỉ phép
        """CREATE TABLE IF NOT EXISTS leave_action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leave_id INTEGER NOT NULL REFERENCES leave_records(id),
            actor_id INTEGER NOT NULL REFERENCES ksnb_staff(id),
            action TEXT NOT NULL,
            comment TEXT,
            from_status TEXT,
            to_status TEXT,
            created_at DATETIME
        )""",
        # 1.3 — bắt buộc đổi mật khẩu lần đầu
        "ALTER TABLE ksnb_staff ADD COLUMN must_change_password BOOLEAN DEFAULT 0",
        # 1.4 — mã IPCAS và username Payment cho KSNB staff (HKV)
        "ALTER TABLE ksnb_staff ADD COLUMN ipcas_code VARCHAR(20)",
        "ALTER TABLE ksnb_staff ADD COLUMN payment_username VARCHAR(50)",
        # 1.5 — gộp SourceUser vào KSNBStaff: thêm staff_id vào document_entries
        "ALTER TABLE document_entries ADD COLUMN staff_id INTEGER REFERENCES ksnb_staff(id)",
        # Backfill staff_id: match source_users.user_code == ksnb_staff.ipcas_code
        """UPDATE document_entries
           SET staff_id = (
               SELECT ks.id FROM ksnb_staff ks
               JOIN source_users su ON trim(ks.ipcas_code) = trim(su.user_code)
               WHERE su.id = document_entries.source_user_id
               LIMIT 1
           )
           WHERE staff_id IS NULL AND source_user_id IS NOT NULL""",
        # 1.6 — unique index mới dùng staff_id (constraint cũ trên source_user_id bị vô hiệu do NULL)
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_entry_staff_date ON document_entries(handover_id, staff_id, transaction_date)",
    ]
    import logging as _logging
    _mig_log = _logging.getLogger(__name__)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        for s in schema_migrations:
            try:
                conn.execute(s)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                msg = str(exc).lower()
                if "duplicate column" not in msg and "already exists" not in msg:
                    if "database is locked" in msg or "locked" in msg:
                        _mig_log.warning("Migration skipped (DB locked, sẽ thử lại lần sau): %.80s", s)
                    else:
                        _mig_log.error("Migration failed: %s — %s", s, exc)
                        raise
    finally:
        conn.close()

    # ── Rebuild handovers: received_by_id NOT NULL → nullable, thêm UNIQUE(dept,date) ──
    _raw = sqlite3.connect(DB_PATH)
    _raw.isolation_level = None  # autocommit để PRAGMA foreign_keys hoạt động
    try:
        _cur = _raw.cursor()
        _cur.execute("PRAGMA table_info(handovers)")
        _h_cols = {r[1]: r[3] for r in _cur.fetchall()}  # {col_name: notnull_flag}
        _cur.execute("PRAGMA index_list(handovers)")
        # origin='u' → UNIQUE constraint (phân biệt với 'c' = CREATE INDEX thường)
        _uniq_ok = any(r[2] and r[3] == 'u' for r in _cur.fetchall())
        _needs_rebuild = bool(_h_cols.get('received_by_id', 0)) or not _uniq_ok
        if _needs_rebuild:
            _mig_log = logging.getLogger(__name__)
            _mig_log.info("Rebuilding handovers table (received_by_id → nullable, UNIQUE added)...")
            _cur.execute("PRAGMA foreign_keys = OFF")
            _cur.execute("PRAGMA legacy_alter_table = ON")
            _cur.execute("BEGIN EXCLUSIVE")
            try:
                _cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='handovers'")
                _tbl_ok = bool(_cur.fetchone())
                _cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='_handovers_bak'")
                _bak_ok = bool(_cur.fetchone())
                if _tbl_ok:
                    if _bak_ok:
                        _cur.execute("DROP TABLE _handovers_bak")
                    _cur.execute("ALTER TABLE handovers RENAME TO _handovers_bak")
                elif not _bak_ok:
                    raise RuntimeError("Không tìm thấy dữ liệu handovers để migrate")
                _cur.execute("""
                    CREATE TABLE handovers (
                        id INTEGER NOT NULL PRIMARY KEY,
                        department_id INTEGER NOT NULL,
                        handover_date DATE NOT NULL,
                        received_by_id INTEGER,
                        delivered_by VARCHAR(100),
                        notes TEXT,
                        status VARCHAR(20),
                        created_at DATETIME,
                        UNIQUE(department_id, handover_date)
                    )
                """)
                _cur.execute("""
                    INSERT INTO handovers
                    SELECT id, department_id, handover_date, received_by_id,
                           delivered_by, notes, status, created_at
                    FROM _handovers_bak
                """)
                _cur.execute("DROP TABLE _handovers_bak")
                _cur.execute("COMMIT")
                logging.getLogger(__name__).info("handovers rebuild hoàn tất")
            except Exception as _me:
                _cur.execute("ROLLBACK")
                logging.getLogger(__name__).error("handovers rebuild thất bại: %s", _me)
                raise
            finally:
                _cur.execute("PRAGMA legacy_alter_table = OFF")
                _cur.execute("PRAGMA foreign_keys = ON")
    finally:
        _raw.close()

    # ── Rebuild document_entries: source_user_id NOT NULL → nullable ────────────
    _raw_de = sqlite3.connect(DB_PATH)
    _raw_de.isolation_level = None
    try:
        _cur_de = _raw_de.cursor()
        _cur_de.execute("PRAGMA table_info(document_entries)")
        _de_notnull = {r[1]: r[3] for r in _cur_de.fetchall()}
        if _de_notnull.get("source_user_id", 0):  # notnull=1 → cần fix
            _mig_log2 = logging.getLogger(__name__)
            _mig_log2.info("Rebuilding document_entries (source_user_id NOT NULL → nullable)...")
            _cur_de.execute("PRAGMA foreign_keys = OFF")
            _cur_de.execute("PRAGMA legacy_alter_table = ON")
            _cur_de.execute("BEGIN EXCLUSIVE")
            try:
                _cur_de.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='_de_bak'")
                if _cur_de.fetchone():
                    _cur_de.execute("DROP TABLE _de_bak")
                _cur_de.execute("ALTER TABLE document_entries RENAME TO _de_bak")
                _cur_de.execute("""
                    CREATE TABLE document_entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        handover_id INTEGER NOT NULL REFERENCES handovers(id),
                        source_user_id INTEGER,
                        transaction_date DATE NOT NULL,
                        sheet_count INTEGER NOT NULL,
                        notes TEXT,
                        entry_status TEXT DEFAULT 'confirmed',
                        entered_by_id INTEGER REFERENCES ksnb_staff(id),
                        confirmed_by_id INTEGER REFERENCES ksnb_staff(id),
                        confirmed_at DATETIME,
                        borrowed_at DATETIME,
                        borrow_reason TEXT,
                        staff_id INTEGER REFERENCES ksnb_staff(id)
                    )
                """)
                _cur_de.execute("INSERT INTO document_entries SELECT * FROM _de_bak")
                _cur_de.execute("DROP TABLE _de_bak")
                _cur_de.execute("COMMIT")
                _mig_log2.info("document_entries rebuild hoàn tất")
            except Exception as _de_err:
                _cur_de.execute("ROLLBACK")
                logging.getLogger(__name__).error("document_entries rebuild thất bại: %s", _de_err)
                raise
            finally:
                _cur_de.execute("PRAGMA legacy_alter_table = OFF")
                _cur_de.execute("PRAGMA foreign_keys = ON")
    finally:
        _raw_de.close()

    index_stmts = [
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_entry_staff_date ON document_entries(handover_id, staff_id, transaction_date)",
        "CREATE INDEX IF NOT EXISTS ix_source_users_dept      ON source_users(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_user        ON document_entries(source_user_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_staff       ON document_entries(staff_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_handover    ON document_entries(handover_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_date        ON document_entries(transaction_date)",
        "CREATE INDEX IF NOT EXISTS ix_handovers_dept          ON handovers(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_handovers_recv          ON handovers(received_by_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_groups_dept      ON bundle_groups(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_groups_creator   ON bundle_groups(created_by_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundles_group           ON bundles(group_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundles_custodian       ON bundles(custodian_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_items_bundle     ON bundle_items(bundle_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_items_entry      ON bundle_items(entry_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_records_staff     ON leave_records(staff_id)",
        "CREATE INDEX IF NOT EXISTS ix_ksnb_staff_dept         ON ksnb_staff(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_status      ON document_entries(entry_status)",
        "CREATE INDEX IF NOT EXISTS ix_entry_change_logs_entry ON entry_change_logs(entry_id)",
        "CREATE INDEX IF NOT EXISTS ix_entry_change_logs_actor ON entry_change_logs(performed_by_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_records_ksv    ON leave_records(ksv_approver_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_records_gd     ON leave_records(gd_approver_id)",
        "CREATE INDEX IF NOT EXISTS ix_delegation_gd        ON delegation_records(giam_doc_id)",
        "CREATE INDEX IF NOT EXISTS ix_delegation_pgd       ON delegation_records(pho_giam_doc_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_records_th     ON leave_records(tong_hop_approver_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_action_logs    ON leave_action_logs(leave_id)",
        "CREATE INDEX IF NOT EXISTS ix_public_holidays_date ON public_holidays(date)",
        "CREATE INDEX IF NOT EXISTS ix_login_logs_username  ON login_logs(username)",
        "CREATE INDEX IF NOT EXISTS ix_login_logs_created   ON login_logs(created_at)",
    ]
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        for s in index_stmts:
            conn.execute(s)
        conn.commit()
    finally:
        conn.close()

_ensure_indexes()

# ── Backup tự động ─────────────────────────────────────────────────────────────
from backend.services.backup_service import start_scheduler as _start_backup
from backend.core.config import settings as _settings
_start_backup(_settings.DATABASE_URL.replace("sqlite:///", ""))

app = FastAPI(
    title="KSNB&HTVH – Agribank",
    description="Hệ thống quản lý nhân sự và chứng từ hậu kiểm",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router)
app.include_router(staff_router)
app.include_router(dept_router)
app.include_router(handover_router)
app.include_router(bundle_router)
app.include_router(leaves_router, prefix="/api/leaves", tags=["leaves"])
app.include_router(delegations_router, prefix="/api/delegations", tags=["delegations"])
app.include_router(logs_router, prefix="/api/admin/logs", tags=["admin-logs"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(holidays_router, prefix="/api/admin/holidays", tags=["holidays"])
app.include_router(reports_router)


_db_log = logging.getLogger("db.contention")

@app.exception_handler(sqlite3.OperationalError)
async def _db_error_handler(request, exc):
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        _db_log.warning("SQLite BUSY — %s %s : %s", request.method, request.url.path, msg)
    else:
        _db_log.error("DB OperationalError — %s %s : %s", request.method, request.url.path, msg)
    return JSONResponse(status_code=503, content={"detail": "Hệ thống bận, vui lòng thử lại"})


@app.get("/")
def root():
    return {"message": "KSNB&HTVH API đang chạy", "docs": "/docs"}
