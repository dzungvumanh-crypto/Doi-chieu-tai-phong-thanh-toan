# Hệ thống KSNB&HTVH – Agribank

Quản lý nhân sự và chứng từ hậu kiểm – Trung tâm Thanh toán Agribank

## Cài đặt

### 1. Yêu cầu
- Python 3.10+
- Windows / Linux / macOS

### 2. Tạo môi trường ảo và cài thư viện

```bash
cd ksnb
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Khởi tạo database

```bash
python init_db.py
```

Kết quả:
```
✓ Database đã khởi tạo thành công!
Tài khoản đăng nhập:
  Admin     : admin / admin123
  Controller: kiensoat1 / ksnb2024
```

### 4. Chạy hệ thống

```bash
python run.py
```

Truy cập:
- **Giao diện web**: http://localhost:8080
- **API docs**: http://localhost:8000/docs
- **Từ máy khác trong LAN**: http://[IP-máy-chủ]:8080

---

## Cấu trúc hệ thống

```
ksnb/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── database.py          # SQLite + SQLAlchemy
│   ├── models.py            # 8 bảng dữ liệu
│   ├── schemas.py           # Pydantic schemas
│   ├── core/
│   │   ├── config.py        # Cấu hình
│   │   ├── security.py      # JWT + bcrypt
│   │   └── deps.py          # FastAPI dependencies
│   ├── api/
│   │   ├── auth.py          # Đăng nhập/đăng xuất
│   │   ├── staff.py         # Quản lý cán bộ KSNB
│   │   ├── departments.py   # Phòng ban + source users
│   │   ├── handovers.py     # Phiếu bàn giao chứng từ
│   │   └── bundles.py       # Gom tập + in bìa
│   └── services/
│       ├── bundle_service.py # ⭐ Thuật toán gom tập
│       └── cover_service.py  # ⭐ Tạo bìa Word (python-docx)
├── frontend/
│   ├── main.py              # NiceGUI app (tất cả pages)
│   └── api_client.py        # HTTP client → backend
├── templates/
│   └── bia_mau_goc.docx    # File mẫu gốc (tham khảo)
├── data/
│   └── ksnb.db             # SQLite database (tự tạo)
├── init_db.py               # Khởi tạo DB + seed data
├── run.py                   # Launcher
└── requirements.txt
```

---

## Chức năng

### Module Nhân sự
- Quản lý cán bộ KSNB (3 cấp quyền: admin, controller, viewer)
- Quản lý user 4 phòng nguồn (Swift, Thanh toán, Kế toán, Nostro&Vostro)
- Theo dõi nghỉ phép

### Module Chứng từ Hậu kiểm
- **Bàn giao**: Tạo phiếu bàn giao theo phòng, nhập số tờ từng user/ngày
- **Gom tập tự động**:
  - Max 350 tờ/tập
  - (user, ngày) không bị tách sang tập khác
  - Nếu 1 ngày > 350 tờ → chia 2 tập cân bằng
- **In bìa**: Tạo file .docx đúng format mẫu (2-column layout)
- **Lưu trữ**: Ghi số hộp, vị trí kệ; tra cứu

---

## Tập số (số La Mã)
- I/I – Tập duy nhất
- I/II, II/II – Chia 2 tập
- I/III, II/III, III/III – Chia 3 tập

---

## Truy cập LAN (nhiều người dùng)
Mở firewall port 8080 và 8000:
```bash
# Windows
netsh advfirewall firewall add rule name="KSNB" dir=in action=allow protocol=TCP localport=8080,8000
```
Người dùng khác truy cập: `http://[IP-máy-chủ]:8080`

---

## Đổi mật khẩu Admin
Đăng nhập → vào trang Nhân sự → chọn tài khoản → Đổi mật khẩu.

Hoặc qua API: `POST /api/auth/change-password`
