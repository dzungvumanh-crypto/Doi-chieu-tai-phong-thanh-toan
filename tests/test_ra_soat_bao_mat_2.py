"""Test hồi quy cho đợt rà soát bảo mật vòng 2 (20/08/2026).

Tiếp nối `tests/test_ra_soat_bao_mat.py` — để file riêng vì file kia đã dài và
khoá một đợt khác. Mỗi lớp dưới đây khoá đúng MỘT lỗ hổng đã vá; gỡ bản vá ra
là test đỏ ngay và tên test nói thẳng hậu quả.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_ra_soat_bao_mat_2.py -v
"""

import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.security import create_access_token, get_password_hash
from backend.database import get_db
from backend.db.migrations import _create_tables
from backend.main import app


_SK = "khoa-phien-thu-nghiem"


def _db_that(tmp_path, must_change=0):
    """DB đủ lược đồ + 1 tài khoản + 1 phiên còn hạn, để chạy get_current_staff THẬT.

    Các test khác trong dự án override get_current_staff bằng dict giả — cách đó
    không kiểm được chính hàm này, mà chốt chặn "phải đổi mật khẩu" lại nằm
    trong đó.
    """
    duong_dan = str(tmp_path / "bm2.db")
    _create_tables(duong_dan)
    conn = sqlite3.connect(duong_dan, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Hai cột này được thêm bằng migration (_ensure_indexes) chứ không nằm trong
    # _create_tables — dựng tay ở đây để test không phụ thuộc DB thật.
    conn.execute("ALTER TABLE login_sessions ADD COLUMN session_key TEXT")
    conn.execute("ALTER TABLE user_tttt ADD COLUMN is_deleted INTEGER DEFAULT 0")
    conn.execute("INSERT INTO departments (id, code, name, is_source) VALUES (1,'P1','Phong 1',1)")
    conn.execute("INSERT INTO departments (id, code, name, is_source) VALUES (2,'P2','Phong 2',1)")
    conn.execute(
        "INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,"
        " username, pwd_hash, is_active, must_change_password) VALUES (?,?,?,?,?,?,?,1,?)",
        (10, "NV010", "Nguoi dung", "chuyen_vien", 1, "nd",
         get_password_hash("MatKhauCu@1"), must_change),
    )
    het_han = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO login_sessions (staff_id, ip_address, expires_at, session_key)"
        " VALUES (?,?,?,?)", (10, "127.0.0.1", het_han, _SK),
    )
    conn.commit()
    return conn


def _client_that(conn):
    def _db():
        yield conn
    app.dependency_overrides[get_db] = _db
    token = create_access_token({"sub": "10", "sk": _SK})
    return TestClient(app), {"Authorization": f"Bearer {token}"}


# ══ 1. Cờ "phải đổi mật khẩu" phải chặn ở BACKEND, không chỉ ở giao diện ══════

class TestBatBuocDoiMatKhau:
    """Trước bản vá, `must_change_password` chỉ được frontend dùng để chuyển
    trang sau khi đăng nhập. Backend vẫn cấp token đầy đủ quyền, nên ai đăng
    nhập bằng mật khẩu mặc định rồi gọi thẳng API — hoặc chỉ cần gõ /home lên
    thanh địa chỉ — là dùng hệ thống bình thường, không bao giờ phải đổi."""

    @pytest.fixture
    def bi_bat_doi(self, tmp_path):
        conn = _db_that(tmp_path, must_change=1)
        client, headers = _client_that(conn)
        yield client, headers
        app.dependency_overrides.clear()
        conn.close()

    @pytest.fixture
    def binh_thuong(self, tmp_path):
        conn = _db_that(tmp_path, must_change=0)
        client, headers = _client_that(conn)
        yield client, headers
        app.dependency_overrides.clear()
        conn.close()

    def test_bi_chan_khi_goi_api_khac(self, bi_bat_doi):
        client, headers = bi_bat_doi
        r = client.get("/api/staff/", headers=headers)
        assert r.status_code == 403
        assert "__must_change_password__" in r.json()["detail"]

    def test_van_vao_duoc_trang_doi_mat_khau(self, bi_bat_doi):
        """Chặn hết thì chính màn hình đổi mật khẩu cũng không chạy được —
        người dùng kẹt cứng, không có đường ra."""
        client, headers = bi_bat_doi
        r = client.post("/api/auth/change-password", headers=headers,
                        json={"old_password": "sai", "new_password": "Abcd@1234"})
        # 400 = đã qua được chốt, chỉ sai mật khẩu cũ. 403 mới là hỏng.
        assert r.status_code == 400

    def test_van_lay_duoc_thong_tin_ban_than(self, bi_bat_doi):
        """/me và /my-features là hai đường layout gọi liên tục."""
        client, headers = bi_bat_doi
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.get("/api/auth/my-features", headers=headers).status_code == 200

    def test_van_dang_xuat_duoc(self, bi_bat_doi):
        client, headers = bi_bat_doi
        assert client.post("/api/auth/logout", headers=headers).status_code == 200

    def test_khong_bi_chan_khi_da_doi(self, binh_thuong):
        """Đối chứng: cờ = 0 thì mọi thứ như cũ — nếu ca này cũng 403 thì test
        ở trên đang xanh vì lý do khác."""
        client, headers = binh_thuong
        assert client.get("/api/staff/", headers=headers).status_code == 200


# ══ 2. Xem hồ sơ từng cán bộ phải theo đúng phạm vi như xem danh sách ═════════

class TestPhamViXemHoSoCanBo:
    """`GET /api/staff/` lọc theo phòng, nhưng `GET /api/staff/{id}` trước đây
    chỉ cần đăng nhập. Đếm id từ 1 đến N là gom được số điện thoại, email, mã
    IPCAS, tên đăng nhập Payment của toàn cơ quan — đi vòng qua đúng bộ lọc vừa
    đặt ở danh sách."""

    @pytest.fixture
    def client(self, tmp_path):
        conn = _db_that(tmp_path)
        # thêm 1 người phòng KHÁC và 1 người CÙNG phòng để so
        conn.execute(
            "INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,"
            " username, pwd_hash, is_active) VALUES (20,'NV020','Phong khac','chuyen_vien',2,'pk','x',1)")
        conn.execute(
            "INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,"
            " username, pwd_hash, is_active) VALUES (21,'NV021','Cung phong','chuyen_vien',1,'cp','x',1)")
        conn.commit()
        client, headers = _client_that(conn)
        yield client, headers
        app.dependency_overrides.clear()
        conn.close()

    def test_khong_xem_duoc_nguoi_phong_khac(self, client):
        c, h = client
        assert c.get("/api/staff/20", headers=h).status_code == 403

    def test_xem_duoc_nguoi_cung_phong(self, client):
        c, h = client
        assert c.get("/api/staff/21", headers=h).status_code == 200

    def test_xem_duoc_chinh_minh(self, client):
        c, h = client
        assert c.get("/api/staff/10", headers=h).status_code == 200


# ══ 3. Header an toàn phải có trên MỌI phản hồi ══════════════════════════════

class TestHeaderAnToan:
    """Không có `X-Frame-Options`/`frame-ancestors` thì kẻ tấn công dựng trang
    mồi, nhúng trang thật vào iframe trong suốt bên trên; người dùng tưởng bấm
    nút trên trang mồi nhưng thực ra bấm nút "Xoá"/"Duyệt" trong phiên đăng
    nhập thật của chính họ."""

    def test_co_du_bon_header(self):
        r = TestClient(app).get("/")
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_khong_gui_hsts_khi_chay_http(self):
        """HSTS trên HTTP thuần: trình duyệt bỏ qua, nhưng nếu lỡ có hiệu lực
        thì nó nhớ vĩnh viễn và từ chối mọi kết nối HTTP tới máy chủ này — không
        gỡ được từ phía máy chủ. Chỉ thêm CÙNG LÚC với TLS."""
        r = TestClient(app).get("/")
        assert "strict-transport-security" not in r.headers
