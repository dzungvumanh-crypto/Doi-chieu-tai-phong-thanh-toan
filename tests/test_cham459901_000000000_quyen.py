"""Test phân quyền của module Chấm TK 459901-1000-000000000, bằng TÀI KHOẢN THƯỜNG.

    menu.cham_459901_000000000    = xem trang, theo dõi tiến độ, tải kết quả
    cham_459901_000000000.process = xử lý file, dừng, xoá kết quả

`test_cham459901_000000000.py` chạy bằng `admin_client` — mà admin bypass mọi feature check nên không
test nào ở đó chạm tới lớp phân quyền (checklist mục B: "luôn thử bằng tài khoản thường"). File này
chạy bằng chuyên viên thật, theo mẫu `test_ach_quyen.py`.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_cham459901_000000000_quyen.py -v
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app
from backend.services import cham459901_000000000_service as svc

_STAFF_ID = 7
_API = "/api/cham459901_000000000"
_MENU = "menu.cham_459901_000000000"
_PROCESS = "cham_459901_000000000.process"


@pytest.fixture(autouse=True)
def _don_tien_do():
    """Xoá sổ tiến độ của module này trước/sau mỗi test (thay cho việc sửa conftest — file của người khác)."""
    svc._progress.clear()
    yield
    svc._progress.clear()


def _client_voi_quyen(codes: list[str]) -> TestClient:
    """TestClient đăng nhập bằng chuyên viên thuộc 1 nhóm được cấp đúng `codes`."""
    # check_same_thread=False: endpoint sync chạy trong threadpool, kết nối tạo ở thread test sẽ
    # bị sqlite từ chối nếu không mở cờ này.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE user_groups (id INTEGER PRIMARY KEY, name TEXT, is_active BOOLEAN DEFAULT 1);
           CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
           CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);
           INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom cham 459901 so 0', 1);"""
    )
    conn.execute("INSERT INTO group_members (group_id, staff_id) VALUES (1, ?)", (_STAFF_ID,))
    conn.executemany(
        "INSERT INTO group_features (group_id, feature_code) VALUES (1, ?)", [(c,) for c in codes],
    )
    conn.commit()

    app.dependency_overrides[get_current_staff] = lambda: {
        "id": _STAFF_ID, "role": StaffRole.CHUYEN_VIEN,
        "username": "test-cv", "full_name": "Test Chuyen Vien",
    }

    def _db():
        yield conn

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client_khong_quyen():
    yield _client_voi_quyen([])
    app.dependency_overrides.clear()


@pytest.fixture
def client_chi_xem():
    yield _client_voi_quyen([_MENU])
    app.dependency_overrides.clear()


@pytest.fixture
def client_duoc_chay():
    yield _client_voi_quyen([_MENU, _PROCESS])
    app.dependency_overrides.clear()


@pytest.fixture
def client_chi_co_quyen_module_cu():
    """Có đủ quyền của module 1000-000007709 nhưng KHÔNG có mã nào của module này."""
    yield _client_voi_quyen(["menu.cham_459901", "cham_459901.process"])
    app.dependency_overrides.clear()


def _pdf():
    return {"files": ("bao_cao.pdf", b"%PDF-1.4", "application/pdf")}


class TestKhongCoQuyenNao:
    def test_moi_cua_deu_bi_tu_choi(self, client_khong_quyen):
        c = client_khong_quyen
        assert c.post(f"{_API}/process", files=_pdf()).status_code == 403
        assert c.get(f"{_API}/progress/x").status_code == 403
        assert c.post(f"{_API}/cancel/x").status_code == 403
        assert c.delete(f"{_API}/result/x").status_code == 403
        assert c.get(f"{_API}/download/x/khac").status_code == 403


class TestChiCoQuyenXem:
    """Có menu nhưng KHÔNG có .process — xem/tải được, không chạy/dừng/xoá được."""

    def test_xem_tien_do_va_tai_ket_qua_khong_bi_chan(self, client_chi_xem):
        # 404 (token không có) chứ không phải 403: qua được cửa quyền
        assert client_chi_xem.get(f"{_API}/progress/khong-co").status_code == 404
        assert client_chi_xem.get(f"{_API}/download/khong-co/khac").status_code == 404

    def test_chay_dung_xoa_bi_tu_choi(self, client_chi_xem):
        assert client_chi_xem.post(f"{_API}/process", files=_pdf()).status_code == 403
        assert client_chi_xem.post(f"{_API}/cancel/x").status_code == 403
        assert client_chi_xem.delete(f"{_API}/result/x").status_code == 403

    def test_bi_tu_choi_truoc_khi_nhan_file_khong_de_lai_luot_chay(self, client_chi_xem):
        client_chi_xem.post(f"{_API}/process", files=_pdf())
        assert svc.luot_dang_chay() is None      # 403 không được chiếm cửa chốt của người khác


class TestDuocChay:
    def test_qua_cua_quyen_toi_kiem_tra_noi_dung(self, client_duoc_chay):
        # file .pdf → 400 "không tìm thấy GL02": đã qua cửa quyền, dừng ở kiểm tra đầu vào (chưa chạy nền)
        r = client_duoc_chay.post(f"{_API}/process", files=_pdf())
        assert r.status_code == 400 and "GL02" in r.json()["detail"]
        assert client_duoc_chay.post(f"{_API}/cancel/khong-co").status_code == 404
        assert client_duoc_chay.delete(f"{_API}/result/khong-co").status_code == 404


class TestHaiModuleKhongDungChungMaQuyen:
    """Hai mã CUSTOMER là hai sổ khác nhau: cấp quyền module cũ không được mở cửa module mới."""

    def test_quyen_module_cu_khong_mo_module_moi(self, client_chi_co_quyen_module_cu):
        c = client_chi_co_quyen_module_cu
        assert c.get(f"{_API}/progress/x").status_code == 403
        assert c.post(f"{_API}/process", files=_pdf()).status_code == 403

    def test_quyen_module_moi_khong_mo_module_cu(self, client_duoc_chay):
        assert client_duoc_chay.get("/api/cham459901/progress/x").status_code == 403
        assert client_duoc_chay.post("/api/cham459901/process", files=_pdf()).status_code == 403
