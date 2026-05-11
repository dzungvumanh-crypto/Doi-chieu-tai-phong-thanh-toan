"""
Khởi tạo database và seed dữ liệu mặc định
Chạy: python init_db.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.database import engine, SessionLocal, Base
from backend.models import Department, KSNBStaff, SourceUser
from backend.core.security import get_password_hash

def init_db():
    # Tạo tất cả tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # ─── Departments ──────────────────────────────────────────────────────
        depts_data = [
            {"code": "BGD",    "name": "Ban Giám đốc",                            "is_source": False},
            {"code": "NOSTRO", "name": "Phòng Quản lý Tài khoản Nostro Vostro", "is_source": True},
            {"code": "SWIFT",  "name": "Phòng Swift",                             "is_source": True},
            {"code": "PAYMENT","name": "Phòng Thanh toán",                        "is_source": True},
            {"code": "ACCT",   "name": "Phòng Kế toán",                           "is_source": True},
            {"code": "KSNB",   "name": "Phòng KSNB&HTVH",  "is_source": False},
            {"code": "TH",     "name": "Phòng Tổng hợp",  "is_source": False},
        ]
        dept_map = {}
        for d in depts_data:
            existing = db.query(Department).filter(Department.code == d["code"]).first()
            if not existing:
                dept = Department(**d)
                db.add(dept)
                db.flush()
                dept_map[d["code"]] = dept.id
                print(f"  + Phòng: {d['name']}")
            else:
                dept_map[d["code"]] = existing.id

        # ─── KSNB Staff (Admin mặc định) ─────────────────────────────────────
        admin_data = [
            {
                "employee_code": "NV001",
                "full_name": "Quản trị viên",
                "role": "admin",
                "username": "admin",
                "password": "Admin@2024!",
            },
            {
                "employee_code": "NV002",
                "full_name": "Kiểm soát viên 1",
                "role": "controller",
                "username": "kiensoat1",
                "password": "Ksnb@2024!",
            },
        ]
        for s in admin_data:
            existing = db.query(KSNBStaff).filter(KSNBStaff.username == s["username"]).first()
            if not existing:
                pwd = s.pop("password")
                staff = KSNBStaff(**s, pwd_hash=get_password_hash(pwd))
                db.add(staff)
                print(f"  + Cán bộ: {staff.full_name} ({staff.username})")

        # ─── Source users mẫu (Phòng Nostro) ─────────────────────────────────
        nostro_users = [
            ("HQBQTRUNG",   "Trungbuiquang"),
            ("HQNKNGAN",    "Ngannguyenthikim18"),
            ("HQNTTVAN",    "Vannguyenthithao"),
            ("HQTTHUONG1",  "Huongtathu"),
            ("HQTTTHIEN1",  "Hientranthithu12"),
            ("HQNTNDIEP1",  "Diepnguyentranngoc"),
            ("HQKHNTLINH",  "Linhnguyenthithuy"),
        ]
        nostro_id = dept_map.get("NOSTRO")
        if nostro_id:
            for code, name in nostro_users:
                existing = db.query(SourceUser).filter(
                    SourceUser.user_code == code,
                    SourceUser.department_id == nostro_id
                ).first()
                if not existing:
                    u = SourceUser(user_code=code, full_name=name, department_id=nostro_id)
                    db.add(u)
                    print(f"  + User: {code} ({name})")

        # ─── Test accounts Chuyên viên ────────────────────────────────────────
        cv_data = [
            {"employee_code": "CV001", "full_name": "GDV Nostro",   "role": "chuyen_vien",
             "username": "gdv_nostro",   "password": "Nostro@2024!", "dept_code": "NOSTRO"},
            {"employee_code": "CV002", "full_name": "GDV Swift",    "role": "chuyen_vien",
             "username": "gdv_swift",    "password": "Swift@2024!",  "dept_code": "SWIFT"},
            {"employee_code": "CV003", "full_name": "GDV Thanh toan","role": "chuyen_vien",
             "username": "gdv_payment",  "password": "Payment@2024!","dept_code": "PAYMENT"},
        ]
        for cv in cv_data:
            existing = db.query(KSNBStaff).filter(KSNBStaff.username == cv["username"]).first()
            if not existing:
                dept_id = dept_map.get(cv.pop("dept_code"))
                pwd     = cv.pop("password")
                staff   = KSNBStaff(**cv, department_id=dept_id, pwd_hash=get_password_hash(pwd))
                db.add(staff)
                print(f"  + Chuyên viên: {staff.full_name} ({staff.username})")

        db.commit()
        print("\n✓ Database đã khởi tạo thành công!")
        print("\nTài khoản đăng nhập mặc định:")
        print("  Admin      : admin / Admin@2024!")
        print("  Controller : kiensoat1 / Ksnb@2024!")
        print("  Chuyên viên: gdv_nostro / Nostro@2024! (NOSTRO)")
        print("  Chuyên viên: gdv_swift / Swift@2024!   (SWIFT)")
        print("  Chuyên viên: gdv_payment / Payment@2024! (PAYMENT)")

    except Exception as e:
        db.rollback()
        print(f"Lỗi: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("Đang khởi tạo database...")
    init_db()
