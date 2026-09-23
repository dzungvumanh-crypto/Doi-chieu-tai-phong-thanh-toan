"""Test tách hai mức quyền của module ACH.

    menu.cham_ach    = xem trang, kiểm tra file, theo dõi tiến độ, tải kết quả
    cham_ach.process = khởi động / tiếp tục / dừng một lần chạy

Toàn bộ test API ACH khác chạy bằng `admin_client` — mà admin bypass mọi
feature check, nên không test nào chạm tới lớp phân quyền này. File này chạy
bằng tài khoản chuyên viên thật để bắt đúng chỗ đó.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_quyen.py -v
"""

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app
from backend.services import ach_service

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


# TestQuyenPhubGop (bản-2, kho 30 ngày) đã xoá cùng Luồng A (23.09.2026) — 3
# endpoint /phub-lichsu, /phub-gop, /phub-gop/{ma}/tai không còn tồn tại.
# Bên dưới là bản-3 (Luồng C, 23.09.2026): POST /phub-gop cần cham_ach.process
# (_CHAY); GET /phub-gop/{ma}/tai chỉ cần menu.cham_ach (_XEM) — đúng khuôn
# 2 mức quyền của module này (xem docstring đầu file).

class TestQuyenPhubGop:
    def test_gop_bi_tu_choi_neu_chi_co_quyen_xem(self, client_chi_xem):
        r = client_chi_xem.post(
            '/api/ach/phub-gop', files={'files': ('a.xlsx', b'x', 'application/vnd.ms-excel')}
        )
        assert r.status_code == 403

    def test_gop_qua_duoc_cua_quyen_neu_co_quyen_chay(self, client_duoc_chay):
        """400 (file không hợp lệ/không nhận diện được loại) chứ KHÔNG phải
        403 — đã qua lớp quyền, chạm tới logic phân loại file thật."""
        r = client_duoc_chay.post(
            '/api/ach/phub-gop', files={'files': ('a.txt', b'x', 'text/plain')}
        )
        assert r.status_code == 400

    def test_tai_ket_qua_van_xem_duoc_chi_voi_quyen_xem(self, client_chi_xem):
        """404 (job/mã không tồn tại) chứ KHÔNG phải 403 — quyền xem vẫn qua,
        giống hệt /download của lượt chạy chính."""
        r = client_chi_xem.get(
            '/api/ach/phub-gop/khong-ton-tai/tai', params={'filename': 'a.xlsx'})
        assert r.status_code == 404


# ─── D4 (23/09/2026) — GET /api/ach/ket-qua + vá /download theo chủ job ───────
# `job_dang_chay()`/`_jobs` là dict TOÀN CỤC trong RAM (backend/services/
# ach_service.py) — không cần dựng job thật qua pipeline, chỉ cần
# `ach_service._new_job(nguoi_tao_id=...)` để test đúng lớp "phạm vi dữ liệu",
# tách khỏi logic pipeline (đã có 467 test khác lo phần đó). PHẠM VI DỮ LIỆU
# theo docs/DESIGN.md — KHÔNG phải quyền, nên KHÔNG cần mã quyền mới, chỉ cần
# 2 người (hoặc admin) có id khác nhau.

_STAFF_A = 7   # trùng _STAFF_ID phía trên — cùng ý nghĩa "1 chuyên viên có quyền"
_STAFF_B = 8
_STAFF_C = 9   # chỉ có menu.cham_ach, KHÔNG có cham_ach.process


def _db_nhieu_nguoi(phan_quyen: dict[int, list[str]]) -> sqlite3.Connection:
    """DB tạm cấp quyền cho NHIỀU staff_id cùng lúc — mỗi id một nhóm riêng,
    dùng chung 1 connection để test không cần dựng lại schema nhiều lần."""
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE user_groups (id INTEGER PRIMARY KEY, name TEXT, is_active BOOLEAN DEFAULT 1);
           CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
           CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);"""
    )
    gid = 1
    for staff_id, codes in phan_quyen.items():
        conn.execute(
            'INSERT INTO user_groups (id, name, is_active) VALUES (?, ?, 1)',
            (gid, f'nhom-{staff_id}'),
        )
        conn.execute('INSERT INTO group_members (group_id, staff_id) VALUES (?, ?)', (gid, staff_id))
        conn.executemany(
            'INSERT INTO group_features (group_id, feature_code) VALUES (?, ?)',
            [(gid, c) for c in codes],
        )
        gid += 1
    conn.commit()
    return conn


def _client_la(staff_id: int, role: str, conn: sqlite3.Connection) -> TestClient:
    """`dependency_overrides` nằm trên chính đối tượng `app` (dùng chung cho mọi
    TestClient) — đổi override TRƯỚC mỗi request mô phỏng đúng "người khác vừa
    đăng nhập", không cần dựng app/`_STAFF_ID` riêng cho từng người."""
    app.dependency_overrides[get_current_staff] = lambda: {
        'id': staff_id, 'role': role,
        'username': f'test-{staff_id}', 'full_name': f'Test {staff_id}',
    }
    def _db():
        yield conn
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def job_gia_lap(monkeypatch, tmp_path):
    """Tạo trực tiếp 1 job ACH 'done' trong bộ nhớ (bỏ qua toàn bộ pipeline
    thật — 467 test khác đã lo phần đó) để test riêng lớp "phạm vi dữ liệu"
    D4. `_don_job_ach` (autouse, tests/conftest.py) tự dọn `ach_service._jobs`
    trước/sau mỗi test, không cần dọn tay ở đây."""
    monkeypatch.setattr(ach_service, 'TEMP_DIR', tmp_path)

    def _tao(nguoi_tao_id: int, ten_file: str = 'doi_chieu_20260101.xlsx',
             ngay: str = '2026-01-01') -> str:
        job_id, job = ach_service._new_job(nguoi_tao_id)
        out_dir = Path(job['output_dir'])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / ten_file).write_bytes(b'noi dung gia lap')
        job['status'] = 'done'
        job['files']  = [ten_file]
        job['ngay']   = ngay
        return job_id

    return _tao


class TestD4KetQuaTheoChuJob:
    """4 mục kiểm tra bắt buộc của PLAN.md mục D4.5 — không chỉ kiểm bằng mắt."""

    def test_nguoi_khac_khong_thay_job_cua_toi(self, job_gia_lap):
        """A chạy job, B đăng nhập → /ket-qua của B KHÔNG thấy job của A."""
        conn = _db_nhieu_nguoi({
            _STAFF_A: ['menu.cham_ach', 'cham_ach.process'],
            _STAFF_B: ['menu.cham_ach', 'cham_ach.process'],
        })
        job_id_a = job_gia_lap(_STAFF_A)
        try:
            r = _client_la(_STAFF_B, StaffRole.CHUYEN_VIEN, conn).get('/api/ach/ket-qua')
            assert r.status_code == 200
            assert all(j['job_id'] != job_id_a for j in r.json())
        finally:
            app.dependency_overrides.clear()

    def test_tai_cheo_job_nguoi_khac_bi_chan(self, job_gia_lap):
        """B biết job_id của A → GET /download trả 404 (không lộ job có tồn
        tại), không trả file."""
        conn = _db_nhieu_nguoi({
            _STAFF_A: ['menu.cham_ach', 'cham_ach.process'],
            _STAFF_B: ['menu.cham_ach', 'cham_ach.process'],
        })
        job_id_a = job_gia_lap(_STAFF_A, ten_file='doi_chieu_20260101.xlsx')
        try:
            r = _client_la(_STAFF_B, StaffRole.CHUYEN_VIEN, conn).get(
                f'/api/ach/download/{job_id_a}/doi_chieu_20260101.xlsx')
            assert r.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_chinh_chu_van_tai_va_thay_job_cua_minh(self, job_gia_lap):
        """Đối chứng của 2 test trên: A KHÔNG bị vạ lây bởi việc chặn B."""
        conn = _db_nhieu_nguoi({_STAFF_A: ['menu.cham_ach', 'cham_ach.process']})
        job_id_a = job_gia_lap(_STAFF_A, ten_file='doi_chieu_20260101.xlsx')
        try:
            client_a = _client_la(_STAFF_A, StaffRole.CHUYEN_VIEN, conn)
            r = client_a.get('/api/ach/ket-qua')
            assert r.status_code == 200
            assert any(j['job_id'] == job_id_a for j in r.json())

            r2 = client_a.get(f'/api/ach/download/{job_id_a}/doi_chieu_20260101.xlsx')
            assert r2.status_code == 200
            assert r2.content == b'noi dung gia lap'
        finally:
            app.dependency_overrides.clear()

    def test_chi_co_quyen_xem_van_tai_duoc_ket_qua_cua_minh(self, job_gia_lap):
        """C chỉ có menu.cham_ach (KHÔNG có cham_ach.process) — vẫn xem/tải
        được kết quả CỦA CHÍNH MÌNH. cham_ach.process chỉ gate việc KHỞI ĐỘNG
        job mới (POST /start), không liên quan tới job đã có sẵn từ trước."""
        conn = _db_nhieu_nguoi({_STAFF_C: ['menu.cham_ach']})
        job_id_c = job_gia_lap(_STAFF_C, ten_file='doi_chieu_20260102.xlsx')
        try:
            client_c = _client_la(_STAFF_C, StaffRole.CHUYEN_VIEN, conn)
            r = client_c.get('/api/ach/ket-qua')
            assert r.status_code == 200
            assert any(j['job_id'] == job_id_c for j in r.json())

            r2 = client_c.get(f'/api/ach/download/{job_id_c}/doi_chieu_20260102.xlsx')
            assert r2.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_sau_khi_don_23h_danh_sach_rong_khong_loi(self, job_gia_lap):
        """Sau khi `_cleanup_old_jobs()` (mốc 23h) dọn job — danh sách rỗng,
        KHÔNG lỗi 500 (job đã biến mất khỏi `_jobs`, không phải một nhánh lỗi
        mới nào cần code riêng để bắt)."""
        conn = _db_nhieu_nguoi({_STAFF_A: ['menu.cham_ach', 'cham_ach.process']})
        job_gia_lap(_STAFF_A)
        ach_service._cleanup_old_jobs(cutoff=time.time() + 1)   # mốc trong tương lai = "đã qua 23h"
        try:
            r = _client_la(_STAFF_A, StaffRole.CHUYEN_VIEN, conn).get('/api/ach/ket-qua')
            assert r.status_code == 200
            assert r.json() == []
        finally:
            app.dependency_overrides.clear()

    def test_admin_mac_dinh_cung_chi_thay_job_cua_chinh_minh(self, job_gia_lap):
        """Suy ra từ D4b (PLAN.md): `require_feature()` cho admin qua CỬA
        QUYỀN ngay lập tức, nhưng KHÔNG tự cấp cho admin quyền THẤY DỮ LIỆU
        của người khác — đây là 2 khái niệm khác nhau (docs/DESIGN.md). Mặc
        định admin cũng chỉ thấy job của chính mình, đúng thiết kế đã chọn."""
        conn = _db_nhieu_nguoi({_STAFF_A: ['menu.cham_ach', 'cham_ach.process']})
        job_id_admin = job_gia_lap(1, ten_file='doi_chieu_20260103.xlsx')   # id=1 = admin (tests/conftest.py::_fake_admin)
        job_id_a     = job_gia_lap(_STAFF_A, ten_file='doi_chieu_20260101.xlsx')
        try:
            client_admin = _client_la(1, StaffRole.ADMIN, conn)
            r = client_admin.get('/api/ach/ket-qua')
            assert r.status_code == 200
            job_ids = [j['job_id'] for j in r.json()]
            assert job_id_admin in job_ids
            assert job_id_a not in job_ids

            # admin vẫn KHÔNG tải được job của người khác qua /download:
            r2 = client_admin.get(f'/api/ach/download/{job_id_a}/doi_chieu_20260101.xlsx')
            assert r2.status_code == 404
        finally:
            app.dependency_overrides.clear()
