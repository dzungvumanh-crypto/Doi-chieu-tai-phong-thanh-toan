"""Schema migrations — _create_tables + _ensure_indexes.

Thêm migration mới: append câu SQL vào cuối list `schema_migrations` trong _ensure_indexes().
Format comment: # Người X — YYYY-MM-DD: mô tả ngắn
Tạo PR riêng, Người 1 approve.
"""
import logging
import sqlite3
from datetime import datetime

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
        """CREATE TABLE IF NOT EXISTS user_tttt (
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
            received_by_id INTEGER REFERENCES user_tttt(id),
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
            entered_by_id INTEGER REFERENCES user_tttt(id),
            confirmed_by_id INTEGER REFERENCES user_tttt(id),
            confirmed_at DATETIME,
            borrowed_at DATETIME,
            borrow_reason TEXT,
            staff_id INTEGER REFERENCES user_tttt(id)
        )""",
        """CREATE TABLE IF NOT EXISTS bundle_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL REFERENCES departments(id),
            total_bundles INTEGER DEFAULT 1,
            created_by_id INTEGER NOT NULL REFERENCES user_tttt(id),
            created_at DATETIME,
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES bundle_groups(id),
            sequence INTEGER NOT NULL,
            total_sheets INTEGER DEFAULT 0,
            custodian_id INTEGER REFERENCES user_tttt(id),
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
            performed_by_id INTEGER NOT NULL REFERENCES user_tttt(id),
            timestamp DATETIME,
            old_sheet_count INTEGER,
            new_sheet_count INTEGER,
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES user_tttt(id),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            leave_type TEXT DEFAULT 'annual',
            reason TEXT,
            status TEXT DEFAULT 'pending_ksv',
            ksv_approver_id INTEGER REFERENCES user_tttt(id),
            ksv_approved_at DATETIME,
            ksv_comment TEXT,
            tong_hop_approver_id INTEGER REFERENCES user_tttt(id),
            tong_hop_approved_at DATETIME,
            tong_hop_comment TEXT,
            gd_approver_id INTEGER REFERENCES user_tttt(id),
            gd_approved_at DATETIME,
            gd_comment TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )""",
        # Session và rate-limit được persist vào DB
        """CREATE TABLE IF NOT EXISTS login_sessions (
            staff_id INTEGER PRIMARY KEY REFERENCES user_tttt(id),
            ip_address TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS login_rate_limit (
            username TEXT PRIMARY KEY,
            attempt_count INTEGER DEFAULT 0,
            window_start TEXT,
            locked_until TEXT
        )""",
        # Audit log cho thao tác admin nhạy cảm
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES user_tttt(id),
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            detail TEXT,
            ip_address TEXT,
            created_at DATETIME
        )""",
        # Phân quyền theo nhóm
        """CREATE TABLE IF NOT EXISTS user_groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        VARCHAR(100) UNIQUE NOT NULL,
            description TEXT,
            is_active   BOOLEAN DEFAULT 1,
            created_at  DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            staff_id INTEGER NOT NULL REFERENCES user_tttt(id)   ON DELETE CASCADE,
            PRIMARY KEY (group_id, staff_id)
        )""",
        """CREATE TABLE IF NOT EXISTS group_features (
            group_id     INTEGER      NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            feature_code VARCHAR(100) NOT NULL,
            PRIMARY KEY (group_id, feature_code)
        )""",
        """CREATE TABLE IF NOT EXISTS swift_recon_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recon_type VARCHAR(10) NOT NULL,
            recon_date DATETIME NOT NULL,
            performed_by_id INTEGER REFERENCES user_tttt(id),
            file_saa_name VARCHAR(255),
            file_ql_name VARCHAR(255),
            total_saa INTEGER,
            total_ql INTEGER,
            total_matched INTEGER,
            total_diff INTEGER,
            merged_json TEXT,
            raw_a_json TEXT,
            raw_b_json TEXT,
            summary_json TEXT,
            diff_a_only_json TEXT,
            diff_b_only_json TEXT,
            di_not_ack_json TEXT,
            created_at DATETIME
        )""",
    ]
    for s in statements:
        cur.execute(s)
    cur.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()


# ── Migrate schema (idempotent) ───────────────────────────────────────────────
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
            giam_doc_id INTEGER NOT NULL REFERENCES user_tttt(id),
            pho_giam_doc_id INTEGER NOT NULL REFERENCES user_tttt(id),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            note TEXT,
            created_by_id INTEGER NOT NULL REFERENCES user_tttt(id),
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
            staff_id INTEGER REFERENCES user_tttt(id),
            ip_address TEXT,
            success INTEGER NOT NULL,
            detail TEXT,
            created_at DATETIME
        )""",
        # Bảng lịch sử thao tác nghỉ phép
        """CREATE TABLE IF NOT EXISTS leave_action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leave_id INTEGER NOT NULL REFERENCES leave_records(id),
            actor_id INTEGER NOT NULL REFERENCES user_tttt(id),
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
        # 2.0 — CHECK constraints cho dữ liệu nghiệp vụ (SQLite cho phép thêm qua trigger thay vì ALTER)
        # Dùng trigger để chặn sheet_count <= 0 khi INSERT/UPDATE
        """CREATE TRIGGER IF NOT EXISTS chk_sheet_count_insert
           BEFORE INSERT ON document_entries
           WHEN NEW.sheet_count <= 0
           BEGIN SELECT RAISE(ABORT, 'sheet_count phải lớn hơn 0'); END""",
        """CREATE TRIGGER IF NOT EXISTS chk_sheet_count_update
           BEFORE UPDATE ON document_entries
           WHEN NEW.sheet_count <= 0
           BEGIN SELECT RAISE(ABORT, 'sheet_count phải lớn hơn 0'); END""",
        # Chặn used_leave_days âm
        """CREATE TRIGGER IF NOT EXISTS chk_used_leave_days
           BEFORE UPDATE ON ksnb_staff
           WHEN NEW.used_leave_days < 0
           BEGIN SELECT RAISE(ABORT, 'used_leave_days không được âm'); END""",
        # Persist session và rate-limit — tồn tại qua restart
        """CREATE TABLE IF NOT EXISTS login_sessions (
            staff_id INTEGER PRIMARY KEY REFERENCES user_tttt(id),
            ip_address TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS login_rate_limit (
            username TEXT PRIMARY KEY,
            attempt_count INTEGER DEFAULT 0,
            window_start TEXT,
            locked_until TEXT
        )""",
        # Audit log cho thao tác admin
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES user_tttt(id),
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            detail TEXT,
            ip_address TEXT,
            created_at DATETIME
        )""",
        # Xóa mềm — ẩn khỏi danh sách nhưng giữ lịch sử
        "ALTER TABLE user_tttt ADD COLUMN is_deleted BOOLEAN DEFAULT 0",
        # Trigger dùng tên bảng mới (idempotent — IF NOT EXISTS)
        """CREATE TRIGGER IF NOT EXISTS chk_used_leave_days
           BEFORE UPDATE ON user_tttt
           WHEN NEW.used_leave_days < 0
           BEGIN SELECT RAISE(ABORT, 'used_leave_days không được âm'); END""",

        # Ngày vào ngành — dùng để tính số ngày phép năm (12 + floor(năm / 4))
        "ALTER TABLE user_tttt ADD COLUMN join_industry_date DATE",

        # ── Thêm migration mới DƯỚI ĐÂY ─────────────────────────────────────────
        # Format: # Người X — YYYY-MM-DD: mô tả ngắn
        # "ALTER TABLE <bảng> ADD COLUMN <cột> <kiểu>",

        # Phân quyền theo nhóm — 2026-06-08
        """CREATE TABLE IF NOT EXISTS user_groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        VARCHAR(100) UNIQUE NOT NULL,
            description TEXT,
            is_active   BOOLEAN DEFAULT 1,
            created_at  DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            staff_id INTEGER NOT NULL REFERENCES user_tttt(id)   ON DELETE CASCADE,
            PRIMARY KEY (group_id, staff_id)
        )""",
        """CREATE TABLE IF NOT EXISTS group_features (
            group_id     INTEGER      NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            feature_code VARCHAR(100) NOT NULL,
            PRIMARY KEY (group_id, feature_code)
        )""",
        # KSNB System — 2026-06-09: session_key để enforce single-session per user
        "ALTER TABLE login_sessions ADD COLUMN session_key TEXT",

        # ── Phân lịch trực Phòng Thanh toán — 2026-06-09 ────────────────────────
        """CREATE TABLE IF NOT EXISTS duty_staff_meta (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL UNIQUE REFERENCES user_tttt(id),
            can_do_sp    BOOLEAN DEFAULT 0,
            is_sp_backup BOOLEAN DEFAULT 0,
            is_on_project BOOLEAN DEFAULT 0,
            display_order INTEGER DEFAULT 999,
            created_at   DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS duty_absences (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id     INTEGER NOT NULL REFERENCES user_tttt(id),
            absence_date DATE    NOT NULL,
            created_at   DATETIME,
            UNIQUE(staff_id, absence_date)
        )""",
        """CREATE TABLE IF NOT EXISTS duty_requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id     INTEGER NOT NULL REFERENCES user_tttt(id),
            request_type VARCHAR(10) NOT NULL CHECK(request_type IN ('once','weekly')),
            specific_date DATE,
            day_of_week  INTEGER,
            year         INTEGER,
            is_active    BOOLEAN DEFAULT 1,
            created_at   DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS duty_special_days (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         DATE    UNIQUE NOT NULL,
            day_type     VARCHAR(20) NOT NULL CHECK(day_type IN ('holiday','cutoff','settlement','makeup')),
            label        VARCHAR(100),
            is_confirmed BOOLEAN DEFAULT 0,
            created_at   DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS duty_rotation_state (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            year        INTEGER NOT NULL,
            role        VARCHAR(20) NOT NULL,
            staff_id    INTEGER NOT NULL REFERENCES user_tttt(id),
            shift_count INTEGER DEFAULT 0,
            last_used   DATE,
            position    INTEGER DEFAULT 0,
            UNIQUE(year, role, staff_id)
        )""",
        """CREATE TABLE IF NOT EXISTS duty_shifts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_date  DATE NOT NULL,
            shift_type  VARCHAR(20) NOT NULL CHECK(shift_type IN ('normal','friday','cutoff','settlement_main','settlement_sub')),
            leader_id   INTEGER REFERENCES user_tttt(id),
            sp_id       INTEGER REFERENCES user_tttt(id),
            sp_warning  VARCHAR(20),
            nv_ids      TEXT DEFAULT '[]',
            nv_count    INTEGER DEFAULT 0,
            is_auto     BOOLEAN DEFAULT 1,
            status      VARCHAR(10) DEFAULT 'draft' CHECK(status IN ('draft','confirmed')),
            created_at  DATETIME,
            UNIQUE(shift_date, shift_type)
        )""",
        """CREATE TABLE IF NOT EXISTS duty_shift_config (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            year        INTEGER UNIQUE NOT NULL,
            nv_count    INTEGER DEFAULT 2,
            signer_name VARCHAR(100)
        )""",
        f"INSERT OR IGNORE INTO duty_shift_config (year, nv_count) VALUES ({datetime.now().year}, 2)",
        "CREATE INDEX IF NOT EXISTS ix_duty_staff_meta_user   ON duty_staff_meta(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_duty_absences_staff    ON duty_absences(staff_id)",
        "CREATE INDEX IF NOT EXISTS ix_duty_absences_date     ON duty_absences(absence_date)",
        "CREATE INDEX IF NOT EXISTS ix_duty_requests_staff    ON duty_requests(staff_id)",
        "CREATE INDEX IF NOT EXISTS ix_duty_rotation_year     ON duty_rotation_state(year, role)",
        "CREATE INDEX IF NOT EXISTS ix_duty_shifts_date       ON duty_shifts(shift_date)",
        # Popup thông báo carry-over hết hiệu lực sau Q1 — mỗi user chỉ xem 1 lần/năm
        "ALTER TABLE user_tttt ADD COLUMN carryover_notice_year INTEGER",
        # Nhập file hạn mức phép (Excel) — lưu lịch sử để có thể hoàn tác
        """CREATE TABLE IF NOT EXISTS quota_import_batches (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            year           INTEGER NOT NULL,
            filename       TEXT,
            imported_by    INTEGER REFERENCES user_tttt(id),
            imported_at    DATETIME,
            row_count      INTEGER DEFAULT 0,
            matched_count  INTEGER DEFAULT 0,
            status         TEXT DEFAULT 'applied' CHECK(status IN ('applied','rolled_back')),
            rolled_back_by INTEGER REFERENCES user_tttt(id),
            rolled_back_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS quota_import_items (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id             INTEGER NOT NULL REFERENCES quota_import_batches(id),
            staff_id             INTEGER NOT NULL REFERENCES user_tttt(id),
            old_quota_days       REAL,
            old_used_leave_days  REAL,
            new_quota_days       REAL,
            new_used_leave_days  REAL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_quota_import_items_batch ON quota_import_items(batch_id)",
    ]
    _mig_log = logging.getLogger(__name__)
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
                if "duplicate column" not in msg and "already exists" not in msg and "no such table" not in msg and "already another table" not in msg:
                    if "database is locked" in msg or "locked" in msg:
                        _mig_log.warning("Migration skipped (DB locked, sẽ thử lại lần sau): %.80s", s)
                    else:
                        _mig_log.error("Migration failed: %s — %s", s, exc)
                        raise
    finally:
        conn.close()

    # ── Rename ksnb_staff → user_tttt (one-time, idempotent) ─────────────────
    _rc = sqlite3.connect(DB_PATH, timeout=30)
    try:
        _existing = {r[0] for r in _rc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "ksnb_staff" in _existing:
            if "user_tttt" in _existing:
                # _create_tables() đã tạo user_tttt rỗng trước — xóa đi để rename
                _rc.execute("DROP TABLE user_tttt")
            _rc.execute("ALTER TABLE ksnb_staff RENAME TO user_tttt")
            _rc.commit()
            logging.getLogger(__name__).info("Đã đổi tên bảng ksnb_staff → user_tttt")
    finally:
        _rc.close()

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
                        entered_by_id INTEGER REFERENCES user_tttt(id),
                        confirmed_by_id INTEGER REFERENCES user_tttt(id),
                        confirmed_at DATETIME,
                        borrowed_at DATETIME,
                        borrow_reason TEXT,
                        staff_id INTEGER REFERENCES user_tttt(id)
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
        "CREATE INDEX IF NOT EXISTS ix_login_logs_created    ON login_logs(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_login_sessions_exp    ON login_sessions(expires_at)",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor      ON audit_logs(actor_id)",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_created    ON audit_logs(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_user_tttt_dept        ON user_tttt(department_id)",
    ]
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        for s in index_stmts:
            try:
                conn.execute(s)
            except Exception as _idx_exc:
                if "already exists" not in str(_idx_exc).lower() and "no such table" not in str(_idx_exc).lower():
                    raise
        conn.commit()
    finally:
        conn.close()
