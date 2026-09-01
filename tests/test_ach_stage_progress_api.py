"""Test stage/progress/summary trong job state + response `GET /api/ach/poll`
(nâng cấp UI 2026-08-21 — stepper + "Kết quả tạm thời" thay cho progress bar suy
đoán ở frontend). 2 lớp:
- Thuật toán thuần: `_bump_stage()` — mapping mốc log → (stage, %), tăng dần.
- API-level: stub `main_from_dir` gọi log_callback/summary_callback với dữ liệu
  mẫu, xác nhận `/api/ach/poll` trả đúng stage/progress/summary cuối cùng.

Cùng pattern admin_client + monkeypatch main_from_dir như test_ach_checkpoint_api.py
— không chạy pipeline thật.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_stage_progress_api.py -v
"""
import os

from backend.services import ach_service as svc
from tests.test_ach_checkpoint_api import _wait_status

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TestBumpStageThuanTuy:
    def test_tang_dan_theo_dung_mốc(self):
        stage, progress = 0, 0.0
        stage, progress = svc._bump_stage(stage, progress, 'Ngày đối chiếu: 01/01/2026')
        assert (stage, progress) == (0, 0.05)
        stage, progress = svc._bump_stage(stage, progress, '[TIMING] Phase 1 IO: 1.0s')
        assert (stage, progress) == (1, 0.45)
        stage, progress = svc._bump_stage(stage, progress, '[TIMING] Phase 2 đối chiếu: 1.0s')
        assert (stage, progress) == (2, 0.65)
        stage, progress = svc._bump_stage(stage, progress, '[EXCEL] (2/4) Ghi sheet: X...')
        assert stage == 3
        assert progress == 0.65 + 0.30 * (2 / 4)
        stage, progress = svc._bump_stage(stage, progress, 'Hoàn thành: /tmp/x.xlsx')
        assert (stage, progress) == (4, 1.0)

    def test_khong_lui_lai_khi_dong_log_khong_theo_thu_tu(self):
        """Dòng log không khớp mốc nào (VD dòng log nghiệp vụ bất kỳ) không được
        làm lùi stage/progress đã đạt được trước đó."""
        stage, progress = svc._bump_stage(2, 0.65, 'Tìm thấy nhóm GW thừa: 3')
        assert (stage, progress) == (2, 0.65)

    def test_dong_khong_khop_marker_nao_giu_nguyen(self):
        stage, progress = svc._bump_stage(0, 0.0, 'Dòng log bất kỳ không có ý nghĩa mốc')
        assert (stage, progress) == (0, 0.0)


def _stub_main_from_dir_co_stage_va_summary(input_dir, output_dir, ngay=None, log_callback=None,
                                            cancel_event=None, dung_sau_mis_di=False,
                                            xac_nhan_path=None, summary_callback=None,
                                            chi_tim_timeout=False):
    """Giả lập main_from_dir chạy thẳng (bo_qua_checkpoint) — phát đủ mốc log
    của cả 5 stage rồi gọi summary_callback với dict mẫu, giống thứ tự thật của
    pipeline.py::main_from_dir/xuat_excel."""
    os.makedirs(output_dir, exist_ok=True)
    if log_callback:
        log_callback('Ngày đối chiếu: 01/01/2026')
        log_callback('[B1] Session: 16282')
        log_callback('Tìm thấy: GL02=1, DI=2, DEN=2')
        log_callback('[TIMING] Phase 1 IO: 0.1s')
        log_callback('[TIMING] Phase 2 đối chiếu: 0.2s')
    if summary_callback:
        summary_callback({'khop_npo_di': 3, 'tien_khop_npo_di': 300_000, 'timeout': 1})
    if log_callback:
        log_callback('[TIMING] Phase 3 Excel: 0.3s')
        log_callback('Hoàn thành: doi_chieu_20260101.xlsx')
    path = os.path.join(output_dir, 'doi_chieu_20260101.xlsx')
    open(path, 'wb').write(b'fake-final')
    return path


class TestPollTraStageProgressSummary:
    def test_poll_tra_dung_stage_progress_summary_khi_done(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir_co_stage_va_summary)

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': '', 'bo_qua_checkpoint': 'true'},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']
        job = _wait_status(job_id, 'done')
        assert job['status'] == 'done'

        poll = admin_client.get(f'/api/ach/poll/{job_id}')
        assert poll.status_code == 200
        body = poll.json()
        assert body['stage'] == 4
        assert body['progress'] == 1.0
        assert body['summary'] == {'khop_npo_di': 3, 'tien_khop_npo_di': 300_000, 'timeout': 1}

    def test_job_moi_tao_mac_dinh_stage_0_progress_0_summary_none(self):
        """Kiểm tra trực tiếp state mặc định của `_new_job()` — không qua HTTP để
        tránh sai lệch do race với thread nền chạy quá nhanh."""
        job_id, job = svc._new_job()
        try:
            assert job['stage'] == 0
            assert job['progress'] == 0.0
            assert job['summary'] is None
        finally:
            with svc._lock:
                svc._jobs.pop(job_id, None)
