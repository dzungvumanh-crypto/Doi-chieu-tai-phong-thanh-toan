"""Test tách hai mức quyền của module ACH.

    menu.cham_ach    = xem trang, kiểm tra file, theo dõi tiến độ, tải kết quả
    cham_ach.process = khởi động / tiếp tục / dừng một lần chạy

Toàn bộ test API ACH khác chạy bằng `admin_client` — mà admin bypass mọi
feature check, nên không test nào chạm tới lớp phân quyền này. File này chạy
bằng tài khoản chuyên viên thật để bắt đúng chỗ đó.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_quyen.py -v
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

_STAFF_ID = 7


def _client_voi_quyen(codes: list[str]) -> TestClient:
    """TestClient đăng nhập bằng chuyên viên thuộc 1 nhóm được cấp đúng `codes`."""
    # check_same_thread=False: FastAPI chạy endpoint sync trong threadpool, kết nối
    # tạo ở thread test sẽ bị sqlite từ chối nếu không mở cờ này.
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE user_groups (id INTEGER PRIMARY KEY, name TEXT, is_active BOOLEAN DEFAULT 1);
           CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
           CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);
           INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom ACH', 1);"""
    )
    conn.execute('INSERT INTO group_members (group_id, staff_id) VALUES (1, ?)', (_STAFF_ID,))
    conn.executemany(
        'INSERT INTO group_features (group_id, feature_code) VALUES (1, ?)',
        [(c,) for c in codes],
    )
    conn.commit()

    app.dependency_overrides[get_current_staff] = lambda: {
        'id': _STAFF_ID, 'role': StaffRole.CHUYEN_VIEN,
        'username': 'test-cv', 'full_name': 'Test Chuyen Vien',
    }
    def _db():
        yield conn

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client_chi_xem():
    yield _client_voi_quyen(['menu.cham_ach'])
    app.dependency_overrides.clear()


@pytest.fixture
def client_duoc_chay():
    yield _client_voi_quyen(['menu.cham_ach', 'cham_ach.process'])
    app.dependency_overrides.clear()


class TestChiCoQuyenXem:
    """Có menu.cham_ach nhưng KHÔNG có cham_ach.process."""

    def test_start_bi_tu_choi(self, client_chi_xem):
        r = client_chi_xem.post(
            '/api/ach/start', files={'files': ('a.pdf', b'x', 'application/pdf')}
        )
        assert r.status_code == 403

    def test_continue_bi_tu_choi(self, client_chi_xem):
        r = client_chi_xem.post(
            '/api/ach/continue/job-khong-co', files={'file': ('a.xlsx', b'x', 'application/vnd.ms-excel')}
        )
        assert r.status_code == 403

    def test_cancel_bi_tu_choi(self, client_chi_xem):
        assert client_chi_xem.post('/api/ach/cancel/job-khong-co').status_code == 403

    def test_van_xem_duoc_tien_do(self, client_chi_xem):
        """404 (job không tồn tại) chứ KHÔNG phải 403 — quyền xem vẫn qua."""
        assert client_chi_xem.get('/api/ach/poll/job-khong-co').status_code == 404

    def test_van_kiem_tra_duoc_file(self, client_chi_xem):
        r = client_chi_xem.post('/api/ach/validate', json={'filenames': ['GL02_x.zip']})
        assert r.status_code == 200

    def test_van_tai_duoc_ket_qua(self, client_chi_xem):
        assert client_chi_xem.get('/api/ach/download/job-khong-co/a.xlsx').status_code == 404


class TestCoQuyenChay:
    def test_start_qua_duoc_cua_quyen(self, client_duoc_chay):
        """400 (không gửi file nào) chứ KHÔNG phải 403 — đã qua lớp quyền."""
        r = client_duoc_chay.post('/api/ach/start', data={'ngay_doi_chieu': ''})
        assert r.status_code in (400, 422)

    def test_cancel_qua_duoc_cua_quyen(self, client_duoc_chay):
        assert client_duoc_chay.post('/api/ach/cancel/job-khong-co').status_code == 404
