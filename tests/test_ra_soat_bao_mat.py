"""Test hồi quy cho đợt rà soát bảo mật / hiệu năng (18/08/2026).

Mỗi lớp dưới đây khoá lại đúng MỘT lỗ hổng đã vá. Nếu ai đó vô tình gỡ bản vá
ra, test tương ứng đỏ ngay và tên test nói thẳng chuyện gì sẽ xảy ra.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_ra_soat_bao_mat.py -v
"""

import asyncio
import io
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile as StarletteUpload

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.core.net import header_ip_dang_tin
from backend.core.uploads import BodySizeLimitMiddleware, read_limited, safe_filename
from backend.database import get_db
from backend.db.migrations import _create_tables
from backend.main import app


# ══ 1. Tên file upload không được nhảy ra ngoài thư mục đích ══════════════════

class TestTenFileUploadAnToan:
    """`Path(thư_mục) / tên_client_gửi` là đường ghi đè file bất kỳ trên ổ đĩa:
    pathlib để đoạn tuyệt đối NUỐT TRỌN đoạn đứng trước. Ghi đè được file .py
    của backend nghĩa là chạy được mã của mình ở lần khởi động lại kế tiếp."""

    @pytest.mark.parametrize("doc_hai", [
        "../../../../../../pwned.txt",
        "..\\..\\..\\pwned.txt",
        "C:/Windows/Temp/pwned.txt",
        "C:\\Windows\\Temp\\pwned.txt",
        "/etc/passwd",
        "..",
        "...",
    ])
    def test_khong_con_thanh_phan_duong_dan(self, doc_hai, tmp_path):
        sach = safe_filename(doc_hai)
        assert "/" not in sach and "\\" not in sach and ":" not in sach
        # Điều kiện thật sự quan trọng: ghép vào thư mục thì vẫn nằm TRONG nó.
        assert (tmp_path / sach).resolve().parent == tmp_path.resolve()

    def test_ten_binh_thuong_giu_nguyen(self):
        assert safe_filename("2026-08_MIS_DI.zip") == "2026-08_MIS_DI.zip"
        assert safe_filename("Báo cáo tháng 8.xlsx") == "Báo cáo tháng 8.xlsx"

    def test_ach_ghi_file_trong_thu_muc_job(self, tmp_path, monkeypatch):
        """Đường ghi thật của ACH — không chỉ hàm làm sạch."""
        from backend.services import ach_service

        monkeypatch.setattr(ach_service, "TEMP_DIR", tmp_path / "temp_ach")
        monkeypatch.setattr(ach_service, "main_from_dir",
                            lambda **kw: str(tmp_path / "ket_qua.xlsx"))

        job_id = ach_service.start_job(
            {"../../../../pwned.txt": b"x", "C:/Windows/Temp/pwned2.txt": b"y"}, None
        )
        job_dir = (tmp_path / "temp_ach" / job_id / "input").resolve()
        ghi_ra = {p.resolve() for p in (tmp_path / "temp_ach").rglob("*") if p.is_file()}
        assert ghi_ra, "không ghi file nào — test tự hỏng, không phải bản vá đúng"
        for p in ghi_ra:
            assert p.parent == job_dir, f"file thoát ra ngoài thư mục job: {p}"
        assert not (tmp_path / "pwned.txt").exists()


# ══ 2. Trần kích thước dữ liệu tải lên ════════════════════════════════════════

class TestTranKichThuoc:
    """Không có trần thì một người tải file vài GB là tiến trình hết RAM và cả
    hệ thống dừng — không cần quyền gì đặc biệt, chỉ cần đăng nhập được."""

    def test_read_limited_dung_lai_khi_vuot(self):
        up = StarletteUpload(filename="to.bin", file=io.BytesIO(b"x" * 5000))
        with pytest.raises(HTTPException) as e:
            asyncio.run(read_limited(up, max_bytes=1000))
        assert e.value.status_code == 413

    def test_read_limited_cho_qua_khi_vua(self):
        up = StarletteUpload(filename="vua.bin", file=io.BytesIO(b"x" * 999))
        assert len(asyncio.run(read_limited(up, max_bytes=1000))) == 999

    def test_middleware_tu_choi_theo_content_length(self):
        async def _app_khong_bao_gio_chay(scope, receive, send):
            raise AssertionError("middleware phải chặn trước khi tới route")

        mw = BodySizeLimitMiddleware(_app_khong_bao_gio_chay, max_bytes=1024)
        da_gui = []

        async def _send(msg):
            da_gui.append(msg)

        async def _receive():
            return {"type": "http.request", "body": b""}

        scope = {"type": "http", "method": "POST", "path": "/api/x",
                 "headers": [(b"content-length", b"99999999")]}
        asyncio.run(mw(scope, _receive, _send))
        assert da_gui[0]["status"] == 413


# ══ 3. Chỉ tin X-Client-IP khi bên gọi là chính máy chủ ═══════════════════════

class TestTinCayHeaderIP:
    """Header ai gửi cũng được. Tin vô điều kiện nghĩa là nhật ký truy vết do
    chính người bị truy vết viết ra."""

    def test_bo_qua_header_tu_may_la(self):
        assert header_ip_dang_tin("192.168.1.50", "10.0.0.1") is None

    def test_nhan_header_tu_localhost(self):
        assert header_ip_dang_tin("127.0.0.1", "192.168.1.77") == "192.168.1.77"

    def test_bo_qua_gia_tri_khong_phai_ip(self):
        """Giá trị này đi thẳng vào cột ip_address rồi hiện lên màn hình nhật ký."""
        assert header_ip_dang_tin("127.0.0.1", "admin da xoa du lieu") is None
        assert header_ip_dang_tin("127.0.0.1", "") is None


# ══ 4. Chặn dò mật khẩu theo địa chỉ máy ═════════════════════════════════════

class TestChanDoMatKhauTheoIP:
    """Đếm theo tên đăng nhập thôi thì đổi tên sau mỗi 4 lần thử là chạy mãi."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE login_rate_limit (
            username TEXT PRIMARY KEY, attempt_count INTEGER DEFAULT 0,
            window_start TEXT, locked_until TEXT)""")
        yield conn
        conn.close()

    def test_rai_mat_khau_qua_nhieu_tai_khoan_van_bi_chan(self, db):
        from backend.core import rate_limit

        ip = "192.168.1.99"
        for i in range(rate_limit.MAX_FAILURES_IP):
            # mỗi lần một tên đăng nhập khác — bộ đếm theo tên không bao giờ chạm ngưỡng
            rate_limit.record_failed_any(db, f"nguoi_dung_{i}", ip)
        assert rate_limit.seconds_locked(db, "nguoi_dung_0") == 0
        assert rate_limit.seconds_locked_any(db, "nguoi_dung_moi", ip) > 0

    def test_dang_nhap_dung_xoa_ca_hai_bo_dem(self, db):
        from backend.core import rate_limit

        rate_limit.record_failed_any(db, "an", "10.0.0.5")
        rate_limit.clear_any(db, "an", "10.0.0.5")
        assert db.execute("SELECT COUNT(*) c FROM login_rate_limit").fetchone()["c"] == 0


# ══ 5. Không leo thang quyền qua màn hình quản lý người dùng ══════════════════

_ID_CV = 50          # chuyên viên, được cấp feature staff.edit / staff.create
_ID_TP = 51          # trưởng phòng, cùng nhóm quyền — dùng làm ca đối chứng
_ID_ADMIN = 1


def _db_nhan_su(tmp_path):
    """DB thật (đủ lược đồ) với 1 chuyên viên có quyền sửa người dùng."""
    duong_dan = str(tmp_path / "ns.db")
    _create_tables(duong_dan)
    conn = sqlite3.connect(duong_dan, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO departments (id, code, name, is_source) VALUES (1,'P1','Phong 1',1)")
    conn.executemany(
        "INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,"
        " username, pwd_hash, is_active) VALUES (?,?,?,?,?,?,'x',1)",
        [(_ID_ADMIN, "NV001", "Quan tri", "admin", None, "admin"),
         (_ID_CV, "NV050", "Chuyen vien", "chuyen_vien", 1, "cv"),
         (_ID_TP, "NV051", "Truong phong", "truong_phong", 1, "tp")],
    )
    conn.execute("INSERT INTO user_groups (id, name, is_active) VALUES (1,'Nhom CV',1)")
    conn.executemany("INSERT INTO group_members (group_id, staff_id) VALUES (1, ?)",
                     [(_ID_CV,), (_ID_TP,)])
    conn.executemany("INSERT INTO group_features (group_id, feature_code) VALUES (1, ?)",
                     [("staff.edit",), ("staff.create",), ("staff.export",)])
    conn.commit()
    return conn


def _client(tmp_path, role, staff_id):
    conn = _db_nhan_su(tmp_path)
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": staff_id, "role": role, "username": "u", "full_name": "Nguoi dung",
    }

    def _db():
        yield conn

    app.dependency_overrides[get_db] = _db
    return TestClient(app), conn


@pytest.fixture
def client_chuyen_vien(tmp_path):
    client, conn = _client(tmp_path, StaffRole.CHUYEN_VIEN, _ID_CV)
    yield client
    app.dependency_overrides.clear()
    conn.close()


@pytest.fixture
def client_truong_phong(tmp_path):
    """Đối chứng: bậc CAO HƠN chuyên viên nên phải sửa được — nếu ca này cũng
    403 thì mấy ca chặn ở trên đang xanh vì lý do khác (vd. hụt feature), không
    phải vì bản vá chạy đúng."""
    client, conn = _client(tmp_path, StaffRole.TRUONG_PHONG, _ID_TP)
    yield client
    app.dependency_overrides.clear()
    conn.close()


class TestKhongLeoThangQuyen:
    """Trước bản vá, rào chắn duy nhất là "QTV cấp 2 không được đụng QTV cấp 1".
    Ai được cấp feature staff.edit — kể cả chuyên viên — đều tự nâng mình lên
    admin bằng một lệnh PUT vào chính id của mình."""

    def test_khong_tu_nang_minh_len_admin(self, client_chuyen_vien):
        r = client_chuyen_vien.put(f"/api/staff/{_ID_CV}", json={"role": "admin"})
        assert r.status_code == 403

    def test_khong_tu_doi_vai_tro_cua_chinh_minh(self, client_chuyen_vien):
        r = client_chuyen_vien.put(f"/api/staff/{_ID_CV}", json={"role": "truong_phong"})
        assert r.status_code == 403

    def test_khong_sua_duoc_tai_khoan_quyen_cao_hon(self, client_chuyen_vien):
        r = client_chuyen_vien.put(f"/api/staff/{_ID_ADMIN}", json={"full_name": "Da chiem"})
        assert r.status_code == 403

    def test_khong_tao_duoc_tai_khoan_admin(self, client_chuyen_vien):
        r = client_chuyen_vien.post("/api/staff/", json={
            "full_name": "Cua sau", "role": "admin",
            "username": "cua_sau", "password": "Abcd@1234",
        })
        assert r.status_code == 403

    def test_khong_tao_duoc_tai_khoan_ngang_bac(self, client_chuyen_vien):
        """Ngang bậc cũng chặn: nếu không thì tạo một chuyên viên khác rồi nâng
        dần lên là đi đường vòng qua đúng cái vừa vá."""
        r = client_chuyen_vien.post("/api/staff/", json={
            "full_name": "Nhan vien moi", "role": "chuyen_vien", "department_id": 1,
            "username": "nv_moi", "password": "Abcd@1234",
        })
        assert r.status_code == 403

    def test_vai_tro_khong_co_that_bi_tu_choi(self, client_chuyen_vien):
        """Gõ sai một ký tự là tài khoản rớt khỏi MỌI kiểm tra quyền, im lặng."""
        r = client_chuyen_vien.put(f"/api/staff/{_ID_CV}", json={"role": "truong_phong "})
        assert r.status_code == 422

    def test_export_db_chi_danh_cho_quan_tri(self, client_chuyen_vien):
        """File này chứa nguyên cột pwd_hash của toàn bộ tài khoản."""
        r = client_chuyen_vien.get("/api/staff/export-db")
        assert r.status_code == 403


class TestVanLamDuocViecHopLe:
    """Đối chứng cho lớp trên — bản vá phải chặn đúng chỗ, không chặn tất cả."""

    def test_truong_phong_sua_duoc_chuyen_vien(self, client_truong_phong):
        r = client_truong_phong.put(f"/api/staff/{_ID_CV}", json={"phone": "0900000000"})
        assert r.status_code == 200, r.text

    def test_truong_phong_van_khong_nang_ai_len_admin(self, client_truong_phong):
        r = client_truong_phong.put(f"/api/staff/{_ID_CV}", json={"role": "admin"})
        assert r.status_code == 403


# ══ 6. Đăng nhập — chạy qua đủ ngăn xếp middleware ═══════════════════════════

_MK = "Test@2026!"


def _db_dang_nhap(tmp_path):
    from backend.core.security import get_password_hash

    duong_dan = str(tmp_path / "auth.db")
    _create_tables(duong_dan)
    conn = sqlite3.connect(duong_dan, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # `login_logs` và cột `session_key` do _ensure_indexes() tạo, mà hàm đó chỉ
    # chạy trên DB_PATH toàn cục nên không áp được cho DB tạm ở đây — dựng tay
    # đúng phần mà luồng đăng nhập cần.
    conn.execute("ALTER TABLE login_sessions ADD COLUMN session_key TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS login_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
        staff_id INTEGER REFERENCES user_tttt(id), ip_address TEXT,
        success INTEGER NOT NULL, detail TEXT, created_at DATETIME)""")
    conn.execute(
        "INSERT INTO user_tttt (id, employee_code, full_name, role, username, pwd_hash,"
        " is_active) VALUES (9, 'NV009', 'Nguoi thu', 'chuyen_vien', 'nguoithu', ?, 1)",
        (get_password_hash(_MK),),
    )
    conn.commit()
    return conn


@pytest.fixture
def app_dang_nhap(tmp_path):
    conn = _db_dang_nhap(tmp_path)

    def _db():
        yield conn

    app.dependency_overrides[get_db] = _db
    yield conn
    app.dependency_overrides.clear()
    conn.close()


def _goi_login(peer: str, body: dict, headers: dict | None = None):
    """Gọi /api/auth/login qua ASGI với địa chỉ máy gọi CHỈ ĐỊNH ĐƯỢC.

    Không dùng TestClient: bản Starlette đang cài (0.35.1) đặt cứng
    `scope["client"] = None`, nên `request.client` luôn rỗng và không thể phân
    biệt "gọi từ chính máy chủ" với "gọi từ máy khác" — đúng cái cần kiểm tra.
    `httpx.ASGITransport` cho khai tham số đó.
    """
    import httpx

    async def _chay():
        transport = httpx.ASGITransport(app=app, client=(peer, 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.post("/api/auth/login", json=body, headers=headers or {})

    return asyncio.run(_chay())


class TestDangNhap:

    def test_dang_nhap_dung_thi_qua(self, app_dang_nhap):
        r = _goi_login("127.0.0.1", {"username": "nguoithu", "password": _MK})
        assert r.status_code == 200, r.text
        assert r.json()["staff_id"] == 9

    def test_may_la_khong_gia_mao_duoc_ip_trong_nhat_ky(self, app_dang_nhap):
        """Máy lạ tự khai mình là 10.9.9.9 — nhật ký phải ghi địa chỉ THẬT."""
        r = _goi_login("192.168.1.200", {"username": "nguoithu", "password": _MK},
                       {"X-Client-IP": "10.9.9.9"})
        assert r.status_code == 200, r.text
        ghi = app_dang_nhap.execute(
            "SELECT ip_address FROM login_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert ghi["ip_address"] == "192.168.1.200"

    def test_frontend_noi_bo_van_chuyen_tiep_duoc_ip_that(self, app_dang_nhap):
        r = _goi_login("127.0.0.1", {"username": "nguoithu", "password": _MK},
                       {"X-Client-IP": "192.168.1.77"})
        assert r.status_code == 200, r.text
        ghi = app_dang_nhap.execute(
            "SELECT ip_address FROM login_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert ghi["ip_address"] == "192.168.1.77"

    def test_sai_nhieu_lan_thi_bi_khoa(self, app_dang_nhap):
        from backend.core import rate_limit

        for _ in range(rate_limit.MAX_FAILURES):
            _goi_login("127.0.0.1", {"username": "nguoithu", "password": "sai"})
        r = _goi_login("127.0.0.1", {"username": "nguoithu", "password": _MK})
        assert r.status_code == 429
