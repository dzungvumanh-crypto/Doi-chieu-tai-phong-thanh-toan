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
        # Lịch sử đổi phòng cán bộ — dùng để định tuyến chứng từ về đúng phòng theo ngày giao dịch
        """CREATE TABLE IF NOT EXISTS staff_department_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES user_tttt(id),
            department_id INTEGER NOT NULL REFERENCES departments(id),
            effective_from DATE NOT NULL,
            created_at DATETIME
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
        # Đối chiếu CITAD 1 ngày = 1 báo cáo CHUNG của cả phòng (không tách
        # theo staff_id nữa — ai lưu sau cùng là bản hiện hành, xem lịch sử
        # từng lần lưu ở bảng doi_chieu_citad_history bên dưới).
        """CREATE TABLE IF NOT EXISTS doi_chieu_citad_sessions (
            ngay        TEXT    PRIMARY KEY,
            data        TEXT    NOT NULL,
            updated_at  DATETIME,
            updated_by  INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL
        )""",
        # Lịch sử từng lần lưu đối chiếu CITAD — 1 dòng/lần bấm Lưu, kèm
        # NGUYÊN VẸN số liệu của phiên chấm đó (không chỉ ai/lúc nào) — để
        # ngày nào nhiều người cùng chấm thì xem/tải lại đúng bản của từng
        # lần lưu, không chỉ biết mỗi tên người lưu.
        """CREATE TABLE IF NOT EXISTS doi_chieu_citad_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ngay        TEXT    NOT NULL,
            staff_id    INTEGER NOT NULL REFERENCES user_tttt(id) ON DELETE CASCADE,
            data        TEXT    NOT NULL,
            created_at  DATETIME NOT NULL
        )""",
        # Mã kết nối Extension cá nhân (thay khoá tĩnh dùng chung sau review
        # bảo mật) — 1 token/staff, chỉ lưu hash, tạo mã mới tự thu hồi mã cũ.
        """CREATE TABLE IF NOT EXISTS doi_chieu_citad_extension_tokens (
            staff_id     INTEGER PRIMARY KEY REFERENCES user_tttt(id) ON DELETE CASCADE,
            token_hash   TEXT NOT NULL UNIQUE,
            created_at   DATETIME,
            last_used_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS doi_soat_citad_history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ngay_cham           VARCHAR(10) NOT NULL,
            recon_date          DATETIME NOT NULL,
            performed_by_id     INTEGER REFERENCES user_tttt(id),
            citad_file_names    TEXT,
            ipcas_file_names    TEXT,
            hub_file_names      TEXT,
            total_citad         INTEGER,
            total_ipcas         INTEGER,
            total_hub           INTEGER,
            n_khop              INTEGER,
            n_lech              INTEGER,
            lech_json           TEXT,
            created_at          DATETIME
        )""",
        # Sổ trực cuối ngày Phòng Thanh toán — KHÔNG tách bảng lịch sử riêng
        # như doi_chieu_citad, bảng này tự thân là lịch sử. `truc_date` KHÔNG
        # unique (khác bản đầu): "từ chối để sửa" ghi đè lên cùng 1 dòng như
        # cũ, nhưng "từ chối để huỷ" (status='cancelled') là NGÕ CỤT — dòng đó
        # đóng vĩnh viễn, phải tạo dòng MỚI (phiên trực khác) cho đúng ngày đó
        # nên 1 ngày có thể có NHIỀU dòng. get_active_by_date() trong service
        # luôn lấy dòng chưa 'cancelled' MỚI NHẤT làm phiên đang làm việc.
        # Luồng: draft -> pending_gdv_confirm -> pending_ksv -> approved | draft (từ chối sửa) | cancelled (từ chối huỷ, ngõ cụt).
        """CREATE TABLE IF NOT EXISTS so_truc_records (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            truc_date         TEXT    NOT NULL,
            gdv1_name         TEXT    DEFAULT '',
            gdv2_name         TEXT    DEFAULT '',
            gdv1_id           INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
            gdv2_id           INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
            ghi_chu           TEXT    DEFAULT '',
            status            TEXT    NOT NULL DEFAULT 'draft',
            initiated_by      INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
            initiated_at      DATETIME,
            ksv_id            INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
            confirmed_by      INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
            confirmed_at      DATETIME,
            ksv_decided_by    INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
            ksv_decided_at    DATETIME,
            reject_reason     TEXT,
            created_at        DATETIME NOT NULL,
            updated_at        DATETIME NOT NULL
        )""",
        # Danh mục chi nhánh thực hiện TTQT — nguồn gốc là file Excel do Phòng
        # KSNB phát hành, nhập vào đây để tra cứu / sửa trực tiếp trên hệ thống.
        # sort_order giữ đúng thứ tự dòng trong file gốc (mã CN không tăng dần).
        """CREATE TABLE IF NOT EXISTS ttqt_branches (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ma_cn        VARCHAR(20) NOT NULL UNIQUE,
            ten_cn       VARCHAR(200) NOT NULL,
            swift_bic    VARCHAR(20),
            loai_cn      INTEGER,
            duoc_phep    VARCHAR(100),
            cn_quan_ly   VARCHAR(200),
            ghi_chu      TEXT,
            sdt          VARCHAR(100),
            dia_chi      TEXT,
            dia_chi_en   TEXT,
            is_closed    INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER,
            updated_at   DATETIME
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
        "ALTER TABLE user_tttt ADD COLUMN department_id INTEGER REFERENCES departments(id)",
        # Cột mới cho DocumentEntry
        "ALTER TABLE document_entries ADD COLUMN entry_status TEXT DEFAULT 'confirmed'",
        "ALTER TABLE document_entries ADD COLUMN entered_by_id INTEGER REFERENCES user_tttt(id)",
        "ALTER TABLE document_entries ADD COLUMN confirmed_by_id INTEGER REFERENCES user_tttt(id)",
        "ALTER TABLE document_entries ADD COLUMN confirmed_at DATETIME",
        "ALTER TABLE document_entries ADD COLUMN borrowed_at DATETIME",
        "ALTER TABLE document_entries ADD COLUMN borrow_reason TEXT",
        # Gán phòng KSNB cho staff cũ không có department_id (idempotent)
        # KHÔNG gán cho 'admin': quản trị viên không thuộc phòng nào (xem migration cuối file).
        "UPDATE user_tttt SET department_id = (SELECT id FROM departments WHERE code = 'KSNB' LIMIT 1) WHERE department_id IS NULL AND role IN ('hau_kiem_vien', 'controller', 'viewer')",
        # Quyền mới — migrate controller → pho_phong
        "ALTER TABLE user_tttt ADD COLUMN annual_leave_days INTEGER DEFAULT 12",
        "ALTER TABLE user_tttt ADD COLUMN used_leave_days INTEGER DEFAULT 0",
        "UPDATE user_tttt SET role = 'pho_phong' WHERE role = 'controller'",
        "UPDATE user_tttt SET role = 'chuyen_vien' WHERE role = 'viewer'",
        "INSERT OR IGNORE INTO departments (code, name, is_source, is_active) VALUES ('TH', 'Phòng Tổng hợp', 0, 1)",
        "INSERT OR IGNORE INTO departments (code, name, is_source, is_active) VALUES ('BGD', 'Ban Giám đốc', 0, 1)",
        # Gán GĐ/PGĐ vào Ban Giám đốc (idempotent — chạy lại không hại)
        "UPDATE user_tttt SET department_id = (SELECT id FROM departments WHERE code = 'BGD' LIMIT 1) WHERE role IN ('giam_doc', 'pho_giam_doc')",
        # Mở rộng LeaveRecord cho workflow 2 bước
        "ALTER TABLE leave_records ADD COLUMN ksv_approver_id INTEGER REFERENCES user_tttt(id)",
        "ALTER TABLE leave_records ADD COLUMN ksv_approved_at DATETIME",
        "ALTER TABLE leave_records ADD COLUMN ksv_comment TEXT",
        "ALTER TABLE leave_records ADD COLUMN gd_approver_id INTEGER REFERENCES user_tttt(id)",
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
        "ALTER TABLE leave_records ADD COLUMN tong_hop_approver_id INTEGER REFERENCES user_tttt(id)",
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
        "ALTER TABLE user_tttt ADD COLUMN must_change_password BOOLEAN DEFAULT 0",
        # 1.4 — mã IPCAS và username Payment cho KSNB staff (HKV)
        "ALTER TABLE user_tttt ADD COLUMN ipcas_code VARCHAR(20)",
        "ALTER TABLE user_tttt ADD COLUMN payment_username VARCHAR(50)",
        # 1.5 — gộp SourceUser vào KSNBStaff: thêm staff_id vào document_entries
        "ALTER TABLE document_entries ADD COLUMN staff_id INTEGER REFERENCES user_tttt(id)",
        # Backfill staff_id: match source_users.user_code == user_tttt.ipcas_code
        """UPDATE document_entries
           SET staff_id = (
               SELECT ks.id FROM user_tttt ks
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
        # (trigger chk_used_leave_days định nghĩa ở dưới, sau khi bảng đã đổi tên)
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
        # (audit_logs đã tạo ở trên — bỏ định nghĩa trùng)
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
        # 2026-08-07: thống nhất 1 cờ song phương duy nhất. Lãnh đạo từng được đánh dấu
        # "Backup SP" nay chuyển thành can_do_sp để không mất khả năng trực song phương.
        # Cột is_sp_backup giữ lại (không drop) nhưng engine/UI không còn đọc.
        #
        # Hai câu này là một cặp: cả list chạy lại MỖI lần khởi động, nên nếu không
        # xoá cờ nguồn thì admin bỏ tick "biết song phương" xong restart là cờ tự bật
        # lại — im lặng, và UI đã gỡ is_sp_backup nên không có cách nào gỡ bằng tay.
        "UPDATE duty_staff_meta SET can_do_sp = 1 WHERE is_sp_backup = 1 AND can_do_sp = 0",
        "UPDATE duty_staff_meta SET is_sp_backup = 0 WHERE is_sp_backup = 1",

        # ── 2026-08-08: khai báo số người trực + ca quyết toán chính/phụ ────────
        # Số người mỗi ca trước đây cứng trong code. Nay phòng tự khai, và số đã
        # khai là bắt buộc — thiếu thì không hình thành ca trực.
        "ALTER TABLE duty_shift_config ADD COLUMN ld_count INTEGER DEFAULT 1",
        "ALTER TABLE duty_shift_config ADD COLUMN qt_ld_count INTEGER DEFAULT 1",
        "ALTER TABLE duty_shift_config ADD COLUMN qt_nv_chinh_count INTEGER DEFAULT 3",
        "ALTER TABLE duty_shift_config ADD COLUMN qt_nv_phu_count INTEGER DEFAULT 2",

        # Một ca có thể có nhiều Lãnh đạo (nhất là ngày quyết toán) → leader_id đơn
        # lẻ không đủ. Cột leader_id giữ lại nhưng engine/API ngừng đọc.
        "ALTER TABLE duty_shifts ADD COLUMN leader_ids TEXT DEFAULT '[]'",
        # Ca quyết toán: nhân viên chia 2 nhóm, nhóm phụ về sớm hơn
        "ALTER TABLE duty_shifts ADD COLUMN nv_phu_ids TEXT DEFAULT '[]'",
        "ALTER TABLE duty_shifts ADD COLUMN nv_phu_count INTEGER DEFAULT 0",
        "UPDATE duty_shifts SET leader_ids = '[' || leader_id || ']' "
        "WHERE leader_id IS NOT NULL AND COALESCE(leader_ids, '[]') = '[]'",

        # Ca quyết toán từng lưu thành 2 dòng (settlement_main + settlement_sub);
        # nay gộp thành 1 ca có nhóm trực phụ. Đổ người của ca phụ vào nv_phu_ids
        # của ca chính cùng ngày rồi xoá dòng phụ.
        """UPDATE duty_shifts SET
               nv_phu_ids = (SELECT s.nv_ids FROM duty_shifts s
                             WHERE s.shift_date = duty_shifts.shift_date
                               AND s.shift_type = 'settlement_sub'),
               nv_phu_count = (SELECT s.nv_count FROM duty_shifts s
                               WHERE s.shift_date = duty_shifts.shift_date
                                 AND s.shift_type = 'settlement_sub')
           WHERE shift_type = 'settlement_main'
             AND COALESCE(nv_phu_ids, '[]') = '[]'
             AND EXISTS (SELECT 1 FROM duty_shifts s
                         WHERE s.shift_date = duty_shifts.shift_date
                           AND s.shift_type = 'settlement_sub')""",
        "DELETE FROM duty_shifts WHERE shift_type = 'settlement_sub'",
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
            new_used_leave_days  REAL,
            created_leave_id     INTEGER
        )""",
        # DB đã tạo bảng trước khi có cột này → thêm bù (lỗi duplicate bị nuốt)
        "ALTER TABLE quota_import_items ADD COLUMN created_leave_id INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_quota_import_items_batch ON quota_import_items(batch_id)",
        # Người 3 — 2026-07-15: bù migration còn thiếu cho leave_records/leave_quotas.
        # Các cột/bảng này đã được thêm out-of-band trên DB dùng để phát triển
        # (không qua migrations.py) nên fresh-install trước đây bị lỗi "no such
        # column"/"no such table" ở /api/leaves/today, khai báo hộ, hạn mức, dashboard.
        "ALTER TABLE leave_records ADD COLUMN spread_dates TEXT",
        "ALTER TABLE leave_records ADD COLUMN is_direct BOOLEAN DEFAULT 0",
        "ALTER TABLE leave_records ADD COLUMN direct_by INTEGER REFERENCES user_tttt(id)",
        "ALTER TABLE leave_records ADD COLUMN recall_reason TEXT",
        """CREATE TABLE IF NOT EXISTS leave_quotas (
            staff_id  INTEGER NOT NULL REFERENCES user_tttt(id),
            year      INTEGER NOT NULL,
            quota_days REAL   NOT NULL DEFAULT 12,
            PRIMARY KEY (staff_id, year)
        )""",
        # year là cột thứ 2 trong PRIMARY KEY (staff_id, year) nên không tận dụng
        # được index khi lọc riêng theo year (get_quotas/export_quotas/stats_annual,
        # _carry_over_bulk) — thêm index riêng cho year.
        "CREATE INDEX IF NOT EXISTS ix_leave_quotas_year ON leave_quotas(year)",

        # ── Lịch sử đổi phòng cán bộ — 2026-07-20 ──────────────────────────────
        # Bảng: mỗi dòng = "từ ngày effective_from, cán bộ thuộc phòng department_id"
        """CREATE TABLE IF NOT EXISTS staff_department_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES user_tttt(id),
            department_id INTEGER NOT NULL REFERENCES departments(id),
            effective_from DATE NOT NULL,
            created_at DATETIME
        )""",
        # Backfill baseline: user chưa có lịch sử → 1 dòng (phòng hiện tại, hiệu lực từ 2000-01-01)
        """INSERT INTO staff_department_history (staff_id, department_id, effective_from, created_at)
           SELECT u.id, u.department_id, '2000-01-01', datetime('now')
           FROM user_tttt u
           WHERE u.department_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM staff_department_history h WHERE h.staff_id = u.id)""",

        # ── Danh sách CN thực hiện TTQT — 2026-08-04 ──────────────────────────
        # Lặp lại DDL của _create_tables() để DB đang chạy cũng có bảng này.
        """CREATE TABLE IF NOT EXISTS ttqt_branches (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ma_cn        VARCHAR(20) NOT NULL UNIQUE,
            ten_cn       VARCHAR(200) NOT NULL,
            swift_bic    VARCHAR(20),
            loai_cn      INTEGER,
            duoc_phep    VARCHAR(100),
            cn_quan_ly   VARCHAR(200),
            ghi_chu      TEXT,
            sdt          VARCHAR(100),
            dia_chi      TEXT,
            dia_chi_en   TEXT,
            is_closed    INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER,
            updated_at   DATETIME
        )""",

        # ── Quản trị viên không thuộc phòng nào — 2026-08-05 ──────────────────
        # Migration cũ (dòng ~292) từng gán KSNB cho role='admin'. Nghiệp vụ sau
        # đó đổi: staff.py ép department_id = NULL cho admin/admin_l2. Hai bên
        # đá nhau → sửa+lưu thì mất phòng, khởi động lại thì phòng hiện về.
        # Dọn cả bảng lịch sử, nếu không admin vẫn bị tính là thành viên KSNB
        # trong báo cáo bàn giao (truy vấn hist ở handovers.py).
        "UPDATE user_tttt SET department_id = NULL WHERE role IN ('admin', 'admin_l2')",
        "DELETE FROM staff_department_history WHERE staff_id IN (SELECT id FROM user_tttt WHERE role IN ('admin', 'admin_l2'))",

        # ── Đồng bộ is_active NULL — 2026-08-11 ───────────────────────────────
        # is_active không NOT NULL và không có DEFAULT nên NULL lọt vào được.
        # Mọi truy vấn đọc đều so `is_active = 1` → NULL vốn đã là "không hoạt
        # động"; ghi hẳn 0 để danh sách user không còn dòng làm hỏng response.
        "UPDATE user_tttt SET is_active = 0 WHERE is_active IS NULL",

        # ── Sổ trực cuối ngày — khoá quyền sửa theo đúng 2 GDV — 2026-08-13 ────
        # gdv1_id/gdv2_id là nguồn sự thật để kiểm tra quyền sửa (chỉ đúng 2
        # người này mới sửa tiếp được) — cột gdv1_name/gdv2_name TEXT cũ không
        # xoá (SQLite ADD COLUMN only) nhưng không còn dùng để đọc/ghi.
        "ALTER TABLE so_truc_records ADD COLUMN gdv1_id INTEGER REFERENCES user_tttt(id)",
        "ALTER TABLE so_truc_records ADD COLUMN gdv2_id INTEGER REFERENCES user_tttt(id)",
    ]
    _mig_log = logging.getLogger(__name__)

    # ── Rename ksnb_staff → user_tttt (one-time, idempotent) ─────────────────
    # PHẢI chạy TRƯỚC schema_migrations: mọi câu SQL trong list dùng tên mới `user_tttt`.
    # Nếu để sau, DB cũ (còn tên `ksnb_staff`) sẽ trượt toàn bộ migration bên dưới.
    _rc = sqlite3.connect(DB_PATH, timeout=30)
    try:
        _existing = {r[0] for r in _rc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "ksnb_staff" in _existing:
            if "user_tttt" in _existing:
                # _create_tables() đã tạo user_tttt rỗng trước — xóa đi để rename.
                # Chỉ xóa khi thật sự rỗng: bảng có dữ liệu nghĩa là tình huống ngoài dự kiến,
                # thà dừng lại còn hơn mất dữ liệu nhân sự.
                _n = _rc.execute("SELECT COUNT(*) FROM user_tttt").fetchone()[0]
                if _n:
                    raise RuntimeError(
                        f"Tồn tại song song 2 bảng: ksnb_staff và user_tttt (user_tttt có {_n} dòng). "
                        "Không tự động gộp — cần xử lý thủ công trước khi khởi động."
                    )
                _rc.execute("DROP TABLE user_tttt")
            _rc.execute("ALTER TABLE ksnb_staff RENAME TO user_tttt")
            _rc.commit()
            _mig_log.info("Đã đổi tên bảng ksnb_staff → user_tttt")
    finally:
        _rc.close()

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
                # Nuốt có chủ đích: migration đã chạy ở lần khởi động trước.
                # KHÔNG thêm "no such table" vào đây — sai tên bảng phải báo lỗi,
                # nếu không migration hỏng sẽ trôi qua im lặng (cột không được thêm).
                if "duplicate column" not in msg and "already exists" not in msg and "already another table" not in msg:
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

    # ── Rebuild doi_chieu_citad_sessions: khoá (ngay, staff_id) → khoá ngay riêng ──
    # CREATE TABLE IF NOT EXISTS ở _create_tables() không làm gì trên DB đã có
    # bảng này với schema CŨ (từ trước khi đổi sang "1 bản ghi CHUNG/ngày") —
    # session_save() mới dùng INSERT ... ON CONFLICT(ngay) sẽ lỗi trên bảng cũ
    # (thiếu cột updated_by, khoá chính không khớp ON CONFLICT(ngay), cột
    # staff_id NOT NULL không được cấp giá trị). SQLite không đổi khoá chính
    # tại chỗ nên phải dựng bảng mới, chép dữ liệu, xoá bảng cũ, đổi tên.
    _raw_dc = sqlite3.connect(DB_PATH)
    _raw_dc.isolation_level = None
    try:
        _cur_dc = _raw_dc.cursor()
        _cur_dc.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='doi_chieu_citad_sessions'")
        if _cur_dc.fetchone():
            _cur_dc.execute("PRAGMA table_info(doi_chieu_citad_sessions)")
            _dc_cols = {r[1] for r in _cur_dc.fetchall()}
            if "staff_id" in _dc_cols:  # dấu hiệu bảng vẫn còn schema cũ
                _mig_log3 = logging.getLogger(__name__)
                _mig_log3.info("Rebuilding doi_chieu_citad_sessions (khoá (ngay, staff_id) → khoá ngay riêng)...")
                _cur_dc.execute("PRAGMA foreign_keys = OFF")
                _cur_dc.execute("PRAGMA legacy_alter_table = ON")
                _cur_dc.execute("BEGIN EXCLUSIVE")
                try:
                    _cur_dc.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_doi_chieu_citad_sessions_bak'"
                    )
                    if _cur_dc.fetchone():
                        _cur_dc.execute("DROP TABLE _doi_chieu_citad_sessions_bak")
                    _cur_dc.execute("ALTER TABLE doi_chieu_citad_sessions RENAME TO _doi_chieu_citad_sessions_bak")
                    _cur_dc.execute("""
                        CREATE TABLE doi_chieu_citad_sessions (
                            ngay        TEXT    PRIMARY KEY,
                            data        TEXT    NOT NULL,
                            updated_at  DATETIME,
                            updated_by  INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL
                        )
                    """)
                    # Bảng cũ có thể nhiều dòng/ngày (1 dòng/staff_id) — mỗi ngày chỉ
                    # giữ lại ĐÚNG 1 dòng: người lưu SAU CÙNG (updated_at lớn nhất,
                    # lệch giờ thì lấy staff_id lớn hơn để có kết quả tất định).
                    _cur_dc.execute("""
                        INSERT INTO doi_chieu_citad_sessions (ngay, data, updated_at, updated_by)
                        SELECT ngay, data, updated_at, staff_id
                        FROM (
                            SELECT ngay, data, updated_at, staff_id,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY ngay ORDER BY updated_at DESC, staff_id DESC
                                   ) AS rn
                            FROM _doi_chieu_citad_sessions_bak
                        )
                        WHERE rn = 1
                    """)
                    _cur_dc.execute("DROP TABLE _doi_chieu_citad_sessions_bak")
                    _cur_dc.execute("COMMIT")
                    _mig_log3.info("doi_chieu_citad_sessions rebuild hoàn tất")
                except Exception as _dc_err:
                    _cur_dc.execute("ROLLBACK")
                    logging.getLogger(__name__).error("doi_chieu_citad_sessions rebuild thất bại: %s", _dc_err)
                    raise
                finally:
                    _cur_dc.execute("PRAGMA legacy_alter_table = OFF")
                    _cur_dc.execute("PRAGMA foreign_keys = ON")
    finally:
        _raw_dc.close()

    # ── Rebuild so_truc_records: bỏ UNIQUE(truc_date) — "từ chối để huỷ" cần
    # cho phép nhiều dòng/ngày (dòng cũ 'cancelled' đóng vĩnh viễn, phải tạo
    # dòng mới cho cùng ngày) — xem comment ở _create_tables() phía trên.
    _raw_st = sqlite3.connect(DB_PATH)
    _raw_st.isolation_level = None
    try:
        _cur_st = _raw_st.cursor()
        _cur_st.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='so_truc_records'")
        if _cur_st.fetchone():
            _cur_st.execute("PRAGMA index_list(so_truc_records)")
            _st_uniq = any(r[2] and r[3] == 'u' for r in _cur_st.fetchall())
            if _st_uniq:
                _mig_log4 = logging.getLogger(__name__)
                _mig_log4.info("Rebuilding so_truc_records (bỏ UNIQUE(truc_date))...")
                _cur_st.execute("PRAGMA foreign_keys = OFF")
                _cur_st.execute("PRAGMA legacy_alter_table = ON")
                _cur_st.execute("BEGIN EXCLUSIVE")
                try:
                    _cur_st.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_so_truc_records_bak'"
                    )
                    if _cur_st.fetchone():
                        _cur_st.execute("DROP TABLE _so_truc_records_bak")
                    _cur_st.execute("ALTER TABLE so_truc_records RENAME TO _so_truc_records_bak")
                    _cur_st.execute("""
                        CREATE TABLE so_truc_records (
                            id                INTEGER PRIMARY KEY AUTOINCREMENT,
                            truc_date         TEXT    NOT NULL,
                            gdv1_name         TEXT    DEFAULT '',
                            gdv2_name         TEXT    DEFAULT '',
                            gdv1_id           INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
                            gdv2_id           INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
                            ghi_chu           TEXT    DEFAULT '',
                            status            TEXT    NOT NULL DEFAULT 'draft',
                            initiated_by      INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
                            initiated_at      DATETIME,
                            ksv_id            INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
                            confirmed_by      INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
                            confirmed_at      DATETIME,
                            ksv_decided_by    INTEGER REFERENCES user_tttt(id) ON DELETE SET NULL,
                            ksv_decided_at    DATETIME,
                            reject_reason     TEXT,
                            created_at        DATETIME NOT NULL,
                            updated_at        DATETIME NOT NULL
                        )
                    """)
                    _cur_st.execute("""
                        INSERT INTO so_truc_records
                        SELECT id, truc_date, gdv1_name, gdv2_name, gdv1_id, gdv2_id, ghi_chu, status,
                               initiated_by, initiated_at, ksv_id, confirmed_by, confirmed_at,
                               ksv_decided_by, ksv_decided_at, reject_reason, created_at, updated_at
                        FROM _so_truc_records_bak
                    """)
                    _cur_st.execute("DROP TABLE _so_truc_records_bak")
                    _cur_st.execute("COMMIT")
                    _mig_log4.info("so_truc_records rebuild hoàn tất")
                except Exception as _st_err:
                    _cur_st.execute("ROLLBACK")
                    logging.getLogger(__name__).error("so_truc_records rebuild thất bại: %s", _st_err)
                    raise
                finally:
                    _cur_st.execute("PRAGMA legacy_alter_table = OFF")
                    _cur_st.execute("PRAGMA foreign_keys = ON")
    finally:
        _raw_st.close()

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
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_status      ON document_entries(entry_status)",
        "CREATE INDEX IF NOT EXISTS ix_entry_change_logs_entry ON entry_change_logs(entry_id)",
        "CREATE INDEX IF NOT EXISTS ix_entry_change_logs_actor ON entry_change_logs(performed_by_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_records_ksv    ON leave_records(ksv_approver_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_records_gd     ON leave_records(gd_approver_id)",
        "CREATE INDEX IF NOT EXISTS ix_doi_soat_citad_history_date ON doi_soat_citad_history(recon_date)",
        "CREATE INDEX IF NOT EXISTS ix_doi_chieu_citad_history_ngay ON doi_chieu_citad_history(ngay)",
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
        "CREATE INDEX IF NOT EXISTS ix_staff_dept_hist       ON staff_department_history(staff_id, effective_from)",
        "CREATE INDEX IF NOT EXISTS ix_ttqt_branches_bic      ON ttqt_branches(swift_bic)",
        "CREATE INDEX IF NOT EXISTS ix_ttqt_branches_sort     ON ttqt_branches(is_closed, sort_order)",
        "CREATE INDEX IF NOT EXISTS ix_so_truc_records_date ON so_truc_records(truc_date)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_so_truc_active_date ON so_truc_records(truc_date) WHERE status != 'cancelled'",
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
