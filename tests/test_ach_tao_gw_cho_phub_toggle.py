"""Test API-level cho chuỗi tham số ô tick "Tạo file GW-cho-pHub" (A4, C1,
23/09/2026) — 4 chỗ bắt buộc: frontend (không test ở đây, xem
frontend/pages/cham_ach.py) → `Form(...)` tường minh ở `/api/ach/start` →
`ach_service.chay_job()` → `main_from_dir()`. Thiếu 1 chỗ là ô tick VÔ TÁC DỤNG
LẶNG LẼ (tiền lệ thật: `ngay_doi_chieu`/`bo_qua_checkpoint`, xem
tests/test_ach_bo_qua_checkpoint.py). Cùng pattern: KHÔNG chạy pipeline thật,
monkeypatch `ach_service.main_from_dir`.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_tao_gw_cho_phub_toggle.py -v
"""
from backend.services import ach_service as svc
from tests.test_ach_checkpoint_api import _wait_status

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _stub_ghi_nhan(cac_lan_goi: list):
    """Ghi lại tao_gw_cho_phub mỗi lần main_from_dir() được gọi — dừng ở
    Checkpoint lần đầu (để test continue_job() gọi lại có giữ đúng lựa chọn
    ban đầu hay không)."""
    def _fn(input_dir, output_dir, ngay=None, log_callback=None, cancel_event=None,
           dung_sau_mis_di=False, xac_nhan_path=None, summary_callback=None,
           tao_gw_cho_phub=False):
        import os
        cac_lan_goi.append(tao_gw_cho_phub)
        os.makedirs(output_dir, exist_ok=True)
        if dung_sau_mis_di:
            path = os.path.join(output_dir, '20260101_ACH_ConfirmMISdi.xlsx')
            open(path, 'wb').write(b'fake-confirm')
            return path
        path = os.path.join(output_dir, 'doi_chieu_20260101.xlsx')
        open(path, 'wb').write(b'fake-final')
        return path
    return _fn


class TestChuoiThamSoTaoGwChoPhub:
    def test_khong_gui_truong_mac_dinh_false(self, admin_client, monkeypatch, tmp_path):
        """Không gửi `tao_gw_cho_phub` trong Form (client cũ/không tick) —
        main_from_dir() phải nhận False, KHÔNG phải giá trị bất kỳ khác."""
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan(cac_lan_goi))

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')
        assert cac_lan_goi == [False]

    def test_tick_bat_truyen_dung_toi_pipeline(self, admin_client, monkeypatch, tmp_path):
        """tao_gw_cho_phub='true' qua Form upload — PHẢI tới được main_from_dir()
        đúng giá trị True (bẫy: route có list[UploadFile], tham số đơn giản
        không khai Form(...) tường minh sẽ luôn bị bỏ qua, xem api/ach.py)."""
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan(cac_lan_goi))

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': '', 'tao_gw_cho_phub': 'true'},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')
        assert cac_lan_goi == [True]

    def test_continue_sau_checkpoint_giu_nguyen_lua_chon_ban_dau(
        self, admin_client, monkeypatch, tmp_path,
    ):
        """Job đi qua Checkpoint (dừng ở awaiting_confirmation) rồi continue —
        continue_job() chạy lại TOÀN BỘ pipeline (không resume state), PHẢI đọc
        lại đúng tao_gw_cho_phub đã chọn ở lần /start đầu tiên (lưu trong
        job['tao_gw_cho_phub']), KHÔNG được âm thầm rơi về mặc định False."""
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan(cac_lan_goi))

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': '', 'tao_gw_cho_phub': 'true'},
        )
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')
        assert cac_lan_goi == [True]   # lần gọi 1 (dừng ở Checkpoint)

        r2 = admin_client.post(
            f'/api/ach/continue/{job_id}',
            files=[('file', ('20260101_ACH_ConfirmMISdi.xlsx', b'da-dien', _XLSX_MIME))],
        )
        assert r2.status_code == 200
        _wait_status(job_id, 'done')
        assert cac_lan_goi == [True, True]   # lần gọi 2 (continue) vẫn giữ True
