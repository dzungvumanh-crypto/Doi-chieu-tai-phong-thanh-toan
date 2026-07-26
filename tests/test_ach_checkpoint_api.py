"""Test API-level cho luồng Checkpoint xác nhận thủ công module ACH (start →
awaiting_confirmation → continue → done), theo pattern admin_client của
tests/conftest.py (xem tests/test_cham459901_api.py). Không chạy pipeline thật —
monkeypatch `ach_service.main_from_dir` để cô lập lớp orchestration (job state
machine) mới thêm ở backend/services/ach_service.py + backend/api/ach.py, vì phần
thuật toán đối chiếu bên trong pipeline đã được test riêng ở test_ach_algorithm.py.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_checkpoint_api.py -v
"""

import time

from backend.services import ach_service as svc

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    - Gọi với dung_sau_khop_gw=True  -> tạo file XacNhan.xlsx giả, dừng ở checkpoint.
    - Gọi với xac_nhan_path đặt      -> tuỳ `xac_nhan_ket_qua`:
        'ok'    -> tạo file doi_chieu_*.xlsx giả, coi như chạy xong.
        'loi'   -> raise ValueError (giả lập file xác nhận điền sai/thiếu).
    """
    def _fn(input_dir, output_dir, ngay=None, log_callback=None, cancel_event=None,
           dung_sau_khop_gw=False, xac_nhan_path=None):
        import os
        os.makedirs(output_dir, exist_ok=True)
        if dung_sau_khop_gw:
            path = os.path.join(output_dir, '20260101_ACH_XacNhan.xlsx')
            open(path, 'wb').write(b'fake-xacnhan')
            return path
        if xac_nhan_path is not None:
            if xac_nhan_ket_qua == 'loi':
                raise ValueError('Còn 1 dòng chưa chọn KET_QUA_XAC_NHAN trong CAN_XAC_NHAN')
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
        assert job['files'] == ['20260101_ACH_XacNhan.xlsx']
        assert job['xac_nhan_file'] == '20260101_ACH_XacNhan.xlsx'

        poll = admin_client.get(f'/api/ach/poll/{job_id}')
        assert poll.status_code == 200
        assert poll.json()['status'] == 'awaiting_confirmation'
        assert poll.json()['files'] == ['20260101_ACH_XacNhan.xlsx']

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
            files=[('file', ('20260101_ACH_XacNhan.xlsx', b'da-dien', _XLSX_MIME))],
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
            files=[('file', ('20260101_ACH_XacNhan.xlsx', b'thieu-chon', _XLSX_MIME))],
        )
        assert r.status_code == 200  # nộp thành công, lỗi phát sinh khi CHẠY (async)

        job = _wait_status(job_id, 'awaiting_confirmation')
        assert job['status'] == 'awaiting_confirmation'
        assert 'KET_QUA_XAC_NHAN' in job['error']
        # File xác nhận gốc vẫn còn để người dùng tải lại sửa, không bị xoá.
        assert job['files'] == ['20260101_ACH_XacNhan.xlsx']

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
