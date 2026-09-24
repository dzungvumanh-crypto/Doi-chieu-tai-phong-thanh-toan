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
from tests.test_ach_phub_gop import _gw_csv_bytes, _phub_xlsx_bytes, _timeout_csv_bytes

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


# PR #136 (review Khánh, 24/09/2026): /phub-gop trước đây chạy phần nặng qua
# asyncio.to_thread() — bể luồng RIÊNG, ngoài mọi giới hạn RAM/số lượt của hệ
# thống. Nay đi qua run_heavy() + chay_tach(phub_gop.gop_phub_tu_file, ...),
# đúng khuôn backend/services/swift_recon/tach.py. Test tĩnh
# (tests/test_doi_chieu_chay_tien_trinh_rieng.py::test_api_khong_dung_asyncio_to_thread)
# đã canh KHÔNG còn asyncio.to_thread trong toàn bộ backend/api/ — ở đây kiểm
# THÊM hành vi thật của endpoint (chạy đúng, dọn sạch input tạm).
class TestPhubGopChayTach:
    def test_gop_that_qua_run_heavy_va_don_sach_thu_muc_tam(
        self, client_duoc_chay, tmp_path, monkeypatch,
    ):
        monkeypatch.setattr(ach_service, 'TEMP_DIR', tmp_path)
        files = [
            ('files', ('pHub.xlsx', _phub_xlsx_bytes([
                {'chi_nhanh': '1400', 'so_thanh_cong': 'MSG_A', 'trace2': '111',
                 'so_tien': '500', 'ngay_gui': '15/09/2026 10:00:00'},
            ]), 'application/vnd.ms-excel')),
            ('files', ('GW_15.csv', _gw_csv_bytes(
                [{'MSGREF': 'MSG_A', 'Ghi chú': 'ACSP:AUTH'}]), 'text/csv')),
            ('files', ('TIMEOUT_15.csv', _timeout_csv_bytes([
                {'CHI_NHANH': '9999', 'TRACE': '999', 'SE_TRACE': '', 'SO_TIEN': '999',
                 'NGAY_DOI_CHIEU': '20260915'},
            ]), 'text/csv')),
        ]
        r = client_duoc_chay.post('/api/ach/phub-gop', files=files)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body['tong_ket'] == {
            'hoan_thanh': 1, 'tt_lenh_loi': 0, 'trang_thai_khac': 0, 'tong': 1}
        assert body['ten_file'] == 'GOP_PHUBLOI_20260915_20260915.xlsx'

        # Kết quả nằm trong TEMP_DIR/<ma>/ — thư mục INPUT tạm (phubgop_in_*)
        # phải đã bị xoá sạch (đúng nguyên tắc "không lưu gì trên server ngoài
        # đúng kết quả cuối", server không giữ lại file người dùng vừa tải lên).
        con_lai = sorted(p.name for p in tmp_path.iterdir())
        assert con_lai == [body['ma']], f"con sot thu muc tam: {con_lai}"

    def test_gop_loi_van_don_sach_thu_muc_tam(self, client_duoc_chay, tmp_path, monkeypatch):
        """File lỗi (400) — thư mục input tạm vẫn phải được dọn (finally),
        không để lại rác trên đĩa mỗi lần người dùng gộp thất bại."""
        monkeypatch.setattr(ach_service, 'TEMP_DIR', tmp_path)
        r = client_duoc_chay.post(
            '/api/ach/phub-gop', files={'files': ('a.txt', b'khong hop le', 'text/plain')})
        assert r.status_code == 400
        assert list(tmp_path.iterdir()) == []


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


# ─── D4 tiếp — vá cùng lớp lỗ hổng ở /poll (23/09/2026, ngoài PLAN.md gốc) ────
# PLAN.md mục D4 chỉ liệt kê /download; /poll bị bỏ ngoài phạm vi lúc đó (xem
# CODE_REPORT.md PHẦN 6, "Quyết định tự chọn" #1) — nay vá nốt cho nhất quán,
# dùng ĐÚNG cách xử lý (job.get('nguoi_tao_id') != current['id'] -> 404).

class TestD4PollTheoChuJob:
    def test_nguoi_khac_khong_poll_duoc_job_cua_toi(self, job_gia_lap):
        """B biết job_id của A -> GET /poll trả 404, không lộ log/tiến trình."""
        conn = _db_nhieu_nguoi({
            _STAFF_A: ['menu.cham_ach', 'cham_ach.process'],
            _STAFF_B: ['menu.cham_ach', 'cham_ach.process'],
        })
        job_id_a = job_gia_lap(_STAFF_A)
        try:
            r = _client_la(_STAFF_B, StaffRole.CHUYEN_VIEN, conn).get(f'/api/ach/poll/{job_id_a}')
            assert r.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_chinh_chu_van_poll_duoc_job_cua_minh(self, job_gia_lap):
        """Đối chứng: A KHÔNG bị vạ lây bởi việc chặn B — vẫn theo dõi tiến
        trình job của chính mình bình thường (đúng luồng _poll() trong
        frontend/pages/cham_ach.py, gọi bằng phiên đăng nhập của chính chủ job)."""
        conn = _db_nhieu_nguoi({_STAFF_A: ['menu.cham_ach', 'cham_ach.process']})
        job_id_a = job_gia_lap(_STAFF_A)
        try:
            r = _client_la(_STAFF_A, StaffRole.CHUYEN_VIEN, conn).get(f'/api/ach/poll/{job_id_a}')
            assert r.status_code == 200
            assert r.json()['status'] == 'done'
        finally:
            app.dependency_overrides.clear()


# ─── D4 tiếp — vá cùng lớp lỗ hổng ở /continue (23/09/2026, ngoài PLAN.md
# gốc) ─────────────────────────────────────────────────────────────────────
# /continue NGUY HIỂM HƠN /poll: cho phép CAN THIỆP CHỦ ĐỘNG (tiếp tục job
# qua Checkpoint của người khác bằng cách nộp file xác nhận), không chỉ đọc
# lén. Dùng đúng khuôn `job.get('nguoi_tao_id') != current['id']` -> 404 đã
# áp dụng ở /download, /poll — không tự bịa cách xử lý riêng.
#
# /cancel KHÔNG còn theo khuôn này — xem TestCancelKhongPhanBietChuJob bên
# dưới (24/09/2026 lượt 2, đảo ngược quyết định lượt 1 sau review Khánh).

class TestD4ContinueTheoChuJob:
    def test_nguoi_khac_khong_tiep_tuc_duoc_job_cua_toi(self, job_gia_lap):
        """B biết job_id của A (đang 'awaiting_confirmation') -> POST
        /continue kèm file trả 404, job của A KHÔNG đổi trạng thái."""
        conn = _db_nhieu_nguoi({
            _STAFF_A: ['menu.cham_ach', 'cham_ach.process'],
            _STAFF_B: ['menu.cham_ach', 'cham_ach.process'],
        })
        job_id_a = job_gia_lap(_STAFF_A)
        ach_service.get_job(job_id_a)['status'] = 'awaiting_confirmation'
        try:
            r = _client_la(_STAFF_B, StaffRole.CHUYEN_VIEN, conn).post(
                f'/api/ach/continue/{job_id_a}',
                files={'file': ('a.xlsx', b'x', 'application/vnd.ms-excel')},
            )
            assert r.status_code == 404
            assert ach_service.get_job(job_id_a)['status'] == 'awaiting_confirmation'
        finally:
            app.dependency_overrides.clear()

    def test_chinh_chu_van_tiep_tuc_duoc_job_cua_minh(self, job_gia_lap, monkeypatch):
        """Đối chứng: A KHÔNG bị vạ lây — qua được lớp kiểm chủ job của
        api/ach.py, tới đúng `ach_service.continue_job()`. `continue_job()`
        thật spawn thread chạy pipeline thật (đã có test riêng cho lớp state
        machine đó ở test_ach_checkpoint_api.py/test_ach_tao_gw_cho_phub_toggle.py)
        — ở đây monkeypatch thành no-op để chỉ kiểm ĐÚNG lớp ownership của
        api/ach.py, không lẫn với việc dựng input_dir/pipeline thật."""
        conn = _db_nhieu_nguoi({_STAFF_A: ['menu.cham_ach', 'cham_ach.process']})
        job_id_a = job_gia_lap(_STAFF_A)
        goi_voi = {}
        monkeypatch.setattr(
            ach_service, 'continue_job',
            lambda job_id, data, filename: goi_voi.update(job_id=job_id))
        try:
            r = _client_la(_STAFF_A, StaffRole.CHUYEN_VIEN, conn).post(
                f'/api/ach/continue/{job_id_a}',
                files={'file': ('a.xlsx', b'x', 'application/vnd.ms-excel')},
            )
            assert r.status_code == 200
            assert goi_voi['job_id'] == job_id_a
        finally:
            app.dependency_overrides.clear()


# ─── /cancel — KHÔNG kiểm chủ job (24/09/2026 lượt 2, review Khánh PR #136) ──
# Đảo ngược quyết định lượt 1 (mã quyền huỷ-hộ riêng + logic đoán "job của ai"
# ở frontend) — logic đoán đó có 2 bug thật (xem
# frontend/pages/cham_ach.py::_thuc_hien_chay()). Quay về hành vi TRƯỚC D4c:
# bất kỳ ai có `cham_ach.process` cũng huỷ được job đang chạy/chờ xác nhận,
# bất kể job của ai — nút "Dừng" chỉ giải phóng chốt dùng chung, không đụng
# dữ liệu (khác /poll, /download, /continue — vẫn CHỈ chủ job, không đổi).
class TestCancelKhongPhanBietChuJob:
    def test_nguoi_khac_cung_huy_duoc_job_dang_cho_xac_nhan(self, job_gia_lap):
        """B không phải chủ job A -> vẫn huỷ được job 'awaiting_confirmation'
        của A (200), job chuyển 'cancelled'."""
        conn = _db_nhieu_nguoi({
            _STAFF_A: ['menu.cham_ach', 'cham_ach.process'],
            _STAFF_B: ['menu.cham_ach', 'cham_ach.process'],
        })
        job_id_a = job_gia_lap(_STAFF_A)
        ach_service.get_job(job_id_a)['status'] = 'awaiting_confirmation'
        try:
            r = _client_la(_STAFF_B, StaffRole.CHUYEN_VIEN, conn).post(f'/api/ach/cancel/{job_id_a}')
            assert r.status_code == 200, r.text
            assert ach_service.get_job(job_id_a)['status'] == 'cancelled'
        finally:
            app.dependency_overrides.clear()

    def test_chinh_chu_van_huy_duoc_job_cua_minh(self, job_gia_lap):
        """Đối chứng: chủ job vẫn huỷ được job đang 'running' của chính mình."""
        conn = _db_nhieu_nguoi({_STAFF_A: ['menu.cham_ach', 'cham_ach.process']})
        job_id_a = job_gia_lap(_STAFF_A)
        ach_service.get_job(job_id_a)['status'] = 'running'
        try:
            r = _client_la(_STAFF_A, StaffRole.CHUYEN_VIEN, conn).post(f'/api/ach/cancel/{job_id_a}')
            assert r.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_khong_co_cham_ach_process_van_403(self, job_gia_lap):
        """Đối chứng: sàn quyền cham_ach.process (require_feature qua _CHAY)
        vẫn áp dụng như cũ — bỏ kiểm chủ job không có nghĩa là bỏ luôn sàn
        quyền chạy (đã có test riêng ở TestChiCoQuyenXem, kiểm lại ở đây cho
        rõ ràng buộc job cụ thể của người khác cũng bị chặn 403 trước khi tới
        logic huỷ)."""
        conn = _db_nhieu_nguoi({
            _STAFF_A: ['menu.cham_ach', 'cham_ach.process'],
            _STAFF_C: ['menu.cham_ach'],
        })
        job_id_a = job_gia_lap(_STAFF_A)
        ach_service.get_job(job_id_a)['status'] = 'running'
        try:
            r = _client_la(_STAFF_C, StaffRole.CHUYEN_VIEN, conn).post(f'/api/ach/cancel/{job_id_a}')
            assert r.status_code == 403
            assert ach_service.get_job(job_id_a)['status'] == 'running'
        finally:
            app.dependency_overrides.clear()

    def test_admin_van_huy_duoc_qua_sieu_quyen_co_san(self, job_gia_lap):
        """admin đi qua require_feature() ở MỌI nơi (siêu quyền có sẵn) —
        không phải hành vi mới, chỉ xác nhận không bị đổi bởi thay đổi này."""
        conn = _db_nhieu_nguoi({_STAFF_A: ['menu.cham_ach', 'cham_ach.process']})
        job_id_a = job_gia_lap(_STAFF_A)
        ach_service.get_job(job_id_a)['status'] = 'running'
        try:
            r = _client_la(1, StaffRole.ADMIN, conn).post(f'/api/ach/cancel/{job_id_a}')
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()
