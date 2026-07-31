"""Test API-level cho luồng Checkpoint xác nhận thủ công tại MIS_đi module ACH
(start → awaiting_confirmation → continue → done), theo pattern admin_client của
tests/conftest.py (xem tests/test_cham459901_api.py). Không chạy pipeline thật —
monkeypatch `ach_service.main_from_dir` để cô lập lớp orchestration (job state
machine) ở backend/services/ach_service.py + backend/api/ach.py, vì phần thuật
toán đối chiếu bên trong pipeline đã được test riêng ở test_ach_algorithm.py.

Điểm 1 (2026-07-31): Checkpoint dời từ sau khop_voi_gw() (xác nhận Timeout) về
ngay sau _process_mis_di() (xác nhận MIS_đi) — file đổi tên
<ngày>_ACH_XacNhan.xlsx → <ngày>_ACH_ConfirmMISdi.xlsx, sheet CAN_XAC_NHAN →
MIS_DI_CONFIRM, cột KET_QUA_XAC_NHAN → LOAI_BO, kwarg dung_sau_khop_gw →
dung_sau_mis_di.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_checkpoint_api.py -v
"""

import time

import pandas as pd
import xlsxwriter

from backend.services import ach_service as svc

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _tao_file_confirm_that(path, so_dong: int, so_tien_moi_dong=100000):
    """Tạo file .xlsx thật với sheet MIS_DI_CONFIRM đúng cấu trúc do
    `pipeline.py::xuat_excel_confirm_mis_di()` sinh ra (header + N dòng dữ liệu +
    vùng ghi chú BỔ SUNG) — dùng để test `_thong_ke_mis_di_can_confirm()` đếm đúng
    số dòng + tổng tiền, không phải đếm ẩu theo tổng số dòng sheet."""
    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet('MIS_DI_CONFIRM')
    header = ['REFHUB', 'MSGREF', 'TRANG_THAI_LENH', 'SO_TIEN', 'LOAI_BO']
    for c, name in enumerate(header):
        ws.write(0, c, name)
    for r in range(so_dong):
        ws.write(r + 1, 0, f'REF{r}')
        ws.write(r + 1, 1, f'MSG{r}')
        ws.write(r + 1, 2, 'TPAY')
        ws.write(r + 1, 3, so_tien_moi_dong)
        ws.write(r + 1, 4, '')
    note_row = so_dong + 2
    ws.write(note_row, 0, 'BỔ SUNG GIAO DỊCH BỊ BỎ SÓT — paste REFHUB vào cột bên dưới')
    ws.write(note_row + 1, 0, 'REFHUB')
    wb.close()


def _wait_status(job_id, until, timeout_s=5):
    """Chờ job['status'] đổi khỏi 'running'/'pending' (thread chạy nền)."""
    deadline = time.time() + timeout_s
    job = None
    while time.time() < deadline:
        job = svc.get_job(job_id)
        if job and job['status'] not in ('pending', 'running'):
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job không đổi trạng thái sau {timeout_s}s: {job}")


def _stub_main_from_dir(*, xac_nhan_ket_qua='ok'):
    """Trả stub thay cho pipeline.main_from_dir thật.
    - Gọi với dung_sau_mis_di=True  -> tạo file ConfirmMISdi.xlsx giả, dừng ở checkpoint.
    - Gọi với xac_nhan_path đặt     -> tuỳ `xac_nhan_ket_qua`:
        'ok'    -> tạo file doi_chieu_*.xlsx giả, coi như chạy xong.
        'loi'   -> raise ValueError (giả lập file xác nhận điền sai/thiếu).
    """
    def _fn(input_dir, output_dir, ngay=None, log_callback=None, cancel_event=None,
           dung_sau_mis_di=False, xac_nhan_path=None):
        import os
        os.makedirs(output_dir, exist_ok=True)
        if dung_sau_mis_di:
            path = os.path.join(output_dir, '20260101_ACH_ConfirmMISdi.xlsx')
            open(path, 'wb').write(b'fake-confirm')
            return path
        if xac_nhan_path is not None:
            if xac_nhan_ket_qua == 'loi':
                raise ValueError('Giá trị LOAI_BO không hợp lệ')
            path = os.path.join(output_dir, 'doi_chieu_20260101.xlsx')
            open(path, 'wb').write(b'fake-final')
            return path
        # Không dùng tới trong luồng checkpoint-always-on, giữ để phòng hờ.
        path = os.path.join(output_dir, 'doi_chieu_20260101.xlsx')
        open(path, 'wb').write(b'fake-final')
        return path
    return _fn


class TestStartLuonDungCheckpoint:
    def test_start_upload_dung_o_checkpoint(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir())

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']

        job = _wait_status(job_id, 'awaiting_confirmation')
        assert job['status'] == 'awaiting_confirmation'
        assert job['files'] == ['20260101_ACH_ConfirmMISdi.xlsx']
        assert job['xac_nhan_file'] == '20260101_ACH_ConfirmMISdi.xlsx'

        poll = admin_client.get(f'/api/ach/poll/{job_id}')
        assert poll.status_code == 200
        assert poll.json()['status'] == 'awaiting_confirmation'
        assert poll.json()['files'] == ['20260101_ACH_ConfirmMISdi.xlsx']

    def test_start_folder_cung_dung_o_checkpoint(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir())
        folder = tmp_path / 'server_folder'
        folder.mkdir()

        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(folder), 'ngay_doi_chieu': ''},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']
        job = _wait_status(job_id, 'awaiting_confirmation')
        assert job['status'] == 'awaiting_confirmation'


class TestContinueSauCheckpoint:
    def _start_and_reach_checkpoint(self, admin_client, monkeypatch, tmp_path,
                                    xac_nhan_ket_qua='ok'):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir(xac_nhan_ket_qua=xac_nhan_ket_qua))
        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')
        return job_id

    def test_continue_thanh_cong_chay_toi_done(self, admin_client, monkeypatch, tmp_path):
        job_id = self._start_and_reach_checkpoint(admin_client, monkeypatch, tmp_path, 'ok')

        r = admin_client.post(
            f'/api/ach/continue/{job_id}',
            files=[('file', ('20260101_ACH_ConfirmMISdi.xlsx', b'da-dien', _XLSX_MIME))],
        )
        assert r.status_code == 200
        assert r.json() == {'ok': True}

        job = _wait_status(job_id, 'done')
        assert job['status'] == 'done'
        assert 'doi_chieu_20260101.xlsx' in job['files']

    def test_continue_loi_xac_nhan_quay_lai_awaiting(self, admin_client, monkeypatch, tmp_path):
        job_id = self._start_and_reach_checkpoint(admin_client, monkeypatch, tmp_path, 'loi')

        r = admin_client.post(
            f'/api/ach/continue/{job_id}',
            files=[('file', ('20260101_ACH_ConfirmMISdi.xlsx', b'thieu-chon', _XLSX_MIME))],
        )
        assert r.status_code == 200  # nộp thành công, lỗi phát sinh khi CHẠY (async)

        job = _wait_status(job_id, 'awaiting_confirmation')
        assert job['status'] == 'awaiting_confirmation'
        assert 'LOAI_BO' in job['error']
        # File xác nhận gốc vẫn còn để người dùng tải lại sửa, không bị xoá.
        assert job['files'] == ['20260101_ACH_ConfirmMISdi.xlsx']

    def test_continue_khi_chua_toi_checkpoint_bao_loi_400(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir())
        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        # Chờ thread nền chạy xong hẳn (tới awaiting_confirmation) rồi mới ép trạng
        # thái 'running' để test nhánh 400 — tránh race với chính thread nền đang
        # tự chuyển trạng thái (đã từng gây flaky khi chạy full suite).
        _wait_status(job_id, 'awaiting_confirmation')
        svc._jobs[job_id]['status'] = 'running'

        r2 = admin_client.post(
            f'/api/ach/continue/{job_id}',
            files=[('file', ('x.xlsx', b'x', _XLSX_MIME))],
        )
        assert r2.status_code == 400

    def test_continue_job_khong_ton_tai_bao_loi_404(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        r = admin_client.post(
            '/api/ach/continue/khong-ton-tai',
            files=[('file', ('x.xlsx', b'x', _XLSX_MIME))],
        )
        assert r.status_code == 404


class TestCancelOChoXacNhan:
    def test_cancel_khi_dang_awaiting_confirmation_thanh_cong_ngay(
        self, admin_client, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir())
        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')

        r2 = admin_client.post(f'/api/ach/cancel/{job_id}')
        assert r2.status_code == 200
        assert r2.json() == {'ok': True}
        assert svc.get_job(job_id)['status'] == 'cancelled'

    def test_cancel_job_da_ket_thuc_bao_loi_404(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        job_id, job = svc._new_job()
        job['status'] = 'done'

        r = admin_client.post(f'/api/ach/cancel/{job_id}')
        assert r.status_code == 404


# ── UX Checkpoint MIS_đi (Điểm 1, 2026-07-31) — đếm "XX GD, YY VND cần xác nhận" ──

class TestThongKeMisDiCanConfirm:
    """`_thong_ke_mis_di_can_confirm()` chỉ phục vụ hiển thị popup — tái dùng đúng
    `_doc_sheet_confirm_mis_di()` đã có, không viết lại logic đọc sheet. Trả về
    (so_luong, tong_tien) thay vì chỉ 1 số như cơ chế cũ."""

    def test_dem_dung_so_dong_va_tong_tien_file_that(self, tmp_path):
        path = tmp_path / 'ConfirmMISdi.xlsx'
        _tao_file_confirm_that(path, so_dong=5, so_tien_moi_dong=100000)
        so_luong, tong_tien = svc._thong_ke_mis_di_can_confirm(str(path))
        assert so_luong == 5
        assert tong_tien == 500000

    def test_dem_0_dong_khi_khong_co_giao_dich(self, tmp_path):
        path = tmp_path / 'ConfirmMISdi.xlsx'
        _tao_file_confirm_that(path, so_dong=0)
        so_luong, tong_tien = svc._thong_ke_mis_di_can_confirm(str(path))
        assert so_luong == 0
        assert tong_tien == 0

    def test_tra_none_khi_file_hong_khong_lam_gian_doan(self, tmp_path):
        path = tmp_path / 'ConfirmMISdi.xlsx'
        path.write_bytes(b'khong-phai-file-excel-that')
        so_luong, tong_tien = svc._thong_ke_mis_di_can_confirm(str(path))
        assert so_luong is None
        assert tong_tien is None


def _stub_main_from_dir_dem_that(so_dong_xac_nhan=3, so_tien_moi_dong=100000):
    """Stub sinh file ConfirmMISdi.xlsx THẬT (không phải bytes giả) để test toàn bộ
    đường đi API → xac_nhan_count/xac_nhan_tong_tien trong poll response."""
    def _fn(input_dir, output_dir, ngay=None, log_callback=None, cancel_event=None,
           dung_sau_mis_di=False, xac_nhan_path=None):
        import os
        os.makedirs(output_dir, exist_ok=True)
        if dung_sau_mis_di:
            path = os.path.join(output_dir, '20260101_ACH_ConfirmMISdi.xlsx')
            _tao_file_confirm_that(path, so_dong=so_dong_xac_nhan, so_tien_moi_dong=so_tien_moi_dong)
            return path
        path = os.path.join(output_dir, 'doi_chieu_20260101.xlsx')
        open(path, 'wb').write(b'fake-final')
        return path
    return _fn


class TestPollTraVeXacNhanCount:
    def test_poll_tra_dung_so_luong_va_tong_tien(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(
            svc, 'main_from_dir',
            _stub_main_from_dir_dem_that(so_dong_xac_nhan=7, so_tien_moi_dong=100000),
        )

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')

        poll = admin_client.get(f'/api/ach/poll/{job_id}')
        body = poll.json()
        assert body['xac_nhan_count'] == 7
        assert body['xac_nhan_tong_tien'] == 700000
        assert body['mode'] == 'upload'
        assert body['final_output_dir'] is None
        assert body['copy_error'] is None


# ── UX Bước 4 (2026-07-27) — copy kết quả về thư mục nguồn (chỉ mode folder) ────

class TestCopyKetQuaVeThuMucNguon:
    def test_mode_folder_copy_thanh_cong(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir(xac_nhan_ket_qua='ok'))
        source_folder = tmp_path / 'du_lieu_nguon'
        source_folder.mkdir()

        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(source_folder), 'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')

        r2 = admin_client.post(
            f'/api/ach/continue/{job_id}',
            files=[('file', ('20260101_ACH_ConfirmMISdi.xlsx', b'da-dien', _XLSX_MIME))],
        )
        assert r2.status_code == 200
        job = _wait_status(job_id, 'done')

        dest = source_folder / 'Output' / 'doi_chieu_20260101.xlsx'
        assert dest.exists()
        assert job['final_output_dir'] == str(source_folder / 'Output')
        assert job['copy_error'] is None

        poll = admin_client.get(f'/api/ach/poll/{job_id}')
        body = poll.json()
        assert body['mode'] == 'folder'
        assert body['final_output_dir'] == str(source_folder / 'Output')

    def test_mode_upload_khong_copy_gi_ca(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir(xac_nhan_ket_qua='ok'))

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')

        r2 = admin_client.post(
            f'/api/ach/continue/{job_id}',
            files=[('file', ('20260101_ACH_ConfirmMISdi.xlsx', b'da-dien', _XLSX_MIME))],
        )
        assert r2.status_code == 200
        job = _wait_status(job_id, 'done')

        assert job['final_output_dir'] is None
        assert job['copy_error'] is None

    def test_copy_loi_van_giu_duoc_ket_qua_qua_download(self, admin_client, monkeypatch, tmp_path):
        """Giả lập ổ đĩa mất kết nối/không ghi được — job vẫn 'done', file gốc vẫn
        tải được qua /api/ach/download, chỉ final_output_dir rỗng + copy_error có nội dung."""
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir(xac_nhan_ket_qua='ok'))
        # Đường dẫn nguồn trỏ tới 1 FILE (không phải thư mục) để mkdir(parents=True) lỗi chắc chắn
        bad_source = tmp_path / 'khong_phai_thu_muc'
        bad_source.write_text('x')

        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(tmp_path), 'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        # Ép source_folder trỏ vào 1 file để buộc copy thất bại — mô phỏng ổ mất
        # kết nối giữa lúc chạy (khó dựng thật trong unit test).
        _wait_status(job_id, 'awaiting_confirmation')
        svc._jobs[job_id]['source_folder'] = str(bad_source)

        r2 = admin_client.post(
            f'/api/ach/continue/{job_id}',
            files=[('file', ('20260101_ACH_ConfirmMISdi.xlsx', b'da-dien', _XLSX_MIME))],
        )
        assert r2.status_code == 200
        job = _wait_status(job_id, 'done')

        assert job['final_output_dir'] is None
        assert job['copy_error']  # có nội dung lỗi, không rỗng
        assert 'doi_chieu_20260101.xlsx' in job['files']

        dl = admin_client.get(f'/api/ach/download/{job_id}/doi_chieu_20260101.xlsx')
        assert dl.status_code == 200
        assert dl.content == b'fake-final'
