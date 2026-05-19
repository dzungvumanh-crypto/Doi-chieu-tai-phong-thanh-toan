"""
Khởi tạo database và seed dữ liệu mặc định
Chạy: python init_db.py

Biến môi trường (tùy chọn):
  ENV                 = development | production  (mặc định: development)
  SEED_ADMIN_PASSWORD = mật khẩu admin đầu tiên  (bắt buộc khi ENV=production)
"""
import sys, os, sqlite3, getpass
sys.path.insert(0, os.path.dirname(__file__))

from backend.core.security import get_password_hash
from backend.database import DB_PATH
from backend.main import _create_tables, _ensure_indexes

_ENV = os.getenv("ENV", "development")


def _get_seed_password(account_label: str, env_key: str, default_dev: str) -> str:
    """Trả mật khẩu seed: từ env, từ prompt (production), hoặc default (development)."""
    from_env = os.getenv(env_key, "")
    if from_env:
        return from_env
    if _ENV == "production":
        pwd = getpass.getpass(f"Nhập mật khẩu cho {account_label}: ").strip()
        if not pwd:
            raise SystemExit(f"Lỗi: mật khẩu cho {account_label} không được để trống ở production")
        return pwd
    return default_dev


def init_db():
    # Tạo tables + migrate schema trước khi mở connection seed
    _create_tables(DB_PATH)
    _ensure_indexes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        # ─── Departments ──────────────────────────────────────────────────────
        depts_data = [
            ("BGD",     "Ban Giám đốc",                            False),
            ("NOSTRO",  "Phòng Quản lý Tài khoản Nostro Vostro",  True),
            ("SWIFT",   "Phòng Swift",                             True),
            ("PAYMENT", "Phòng Thanh toán",                        True),
            ("ACCT",    "Phòng Kế toán",                           True),
            ("KSNB",    "Phòng KSNB&HTVH",                        False),
            ("TH",      "Phòng Tổng hợp",                         False),
        ]
        dept_map = {}
        for code, name, is_source in depts_data:
            row = conn.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()
            if not row:
                cur = conn.execute(
                    "INSERT INTO departments(code, name, is_source, is_active) VALUES(?,?,?,1)",
                    (code, name, int(is_source)),
                )
                dept_map[code] = cur.lastrowid
                print(f"  + Phòng: {name}")
            else:
                dept_map[code] = row["id"]

        # ─── KSNB Staff (Admin mặc định) ─────────────────────────────────────
        admin_pwd = _get_seed_password("admin", "SEED_ADMIN_PASSWORD", "Admin@2024!")
        admin_data = [
            ("NV001", "Quản trị viên",    "admin",     "admin",     admin_pwd,  None),
            ("NV002", "Kiểm soát viên 1", "pho_phong", "kiensoat1",
             _get_seed_password("kiensoat1", "SEED_KSV_PASSWORD", "Ksnb@2024!"), None),
        ]
        for emp_code, full_name, role, username, pwd, dept_code in admin_data:
            row = conn.execute("SELECT id FROM user_tttt WHERE username = ?", (username,)).fetchone()
            if not row:
                dept_id = dept_map.get(dept_code) if dept_code else None
                conn.execute(
                    """INSERT INTO user_tttt
                       (employee_code, full_name, role, username, pwd_hash,
                        department_id, is_active, must_change_password)
                       VALUES(?,?,?,?,?,?,1,1)""",
                    (emp_code, full_name, role, username, get_password_hash(pwd), dept_id),
                )
                print(f"  + Cán bộ: {full_name} ({username})")

        # ─── Test accounts Chuyên viên (chỉ seed ở development) ──────────────
        if _ENV != "production":
            cv_data = [
                ("CV001", "GDV Nostro",     "chuyen_vien", "gdv_nostro",  "Nostro@2024!",  "NOSTRO"),
                ("CV002", "GDV Swift",      "chuyen_vien", "gdv_swift",   "Swift@2024!",   "SWIFT"),
                ("CV003", "GDV Thanh toán", "chuyen_vien", "gdv_payment", "Payment@2024!", "PAYMENT"),
            ]
            for emp_code, full_name, role, username, pwd, dept_code in cv_data:
                row = conn.execute("SELECT id FROM user_tttt WHERE username = ?", (username,)).fetchone()
                if not row:
                    dept_id = dept_map.get(dept_code)
                    conn.execute(
                        """INSERT INTO user_tttt
                           (employee_code, full_name, role, username, pwd_hash,
                            department_id, is_active, must_change_password)
                           VALUES(?,?,?,?,?,?,1,1)""",
                        (emp_code, full_name, role, username, get_password_hash(pwd), dept_id),
                    )
                    print(f"  + Chuyên viên test: {full_name} ({username})")

        conn.commit()
        print("\n✓ Database đã khởi tạo thành công!")
        print("\nTài khoản đã tạo:")
        print("  admin, kiensoat1", end="")
        if _ENV != "production":
            print(", gdv_nostro, gdv_swift, gdv_payment (chỉ development)")
        else:
            print()
        print("\n⚠️  Tất cả tài khoản bắt buộc đổi mật khẩu khi đăng nhập lần đầu!")

    except Exception as e:
        conn.rollback()
        print(f"Lỗi: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("Đang khởi tạo database...")
    init_db()
