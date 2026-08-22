"""Test API-level cho tính năng "chạy thẳng, bỏ qua Checkpoint" (2026-07-31, xem
memory project_ach_chay_thang_bo_qua_checkpoint) — cờ bo_qua_checkpoint=True
khiến main_from_dir() được gọi với dung_sau_mis_di=False ngay từ LẦN CHẠY ĐẦU
TIÊN, job đi thẳng tới 'done' thay vì dừng ở 'awaiting_confirmation'. Mặc định
(bo_qua_checkpoint=False/không truyền) hành vi Checkpoint bắt buộc giữ nguyên
— đây là nhánh đã có test riêng ở test_ach_checkpoint_api.py, ở đây chỉ thêm
test hồi quy xác nhận KHÔNG bị đổi hành vi mặc định.

Không chạy pipeline thật — monkeypatch `ach_service.main_from_dir`, cùng
pattern test_ach_checkpoint_api.py.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_bo_qua_checkpoint.py -v
"""

from backend.services import ach_service as svc
from tests.test_ach_checkpoint_api import _wait_status

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _stub_ghi_nhan_tham_so(cac_lan_goi: list):
    """Ghi lại (ngay, dung_sau_mis_di) mỗi lần gọi — dùng để kiểm tra
    `ngay_doi_chieu` có thật sự tới được main_from_dir() qua mode upload hay
    không (xem regression bug Form() bên dưới)."""
    def _fn(input_dir, output_dir, ngay=None, log_callback=None, cancel_event=None,
           dung_sau_mis_di=False, xac_nhan_path=None, summary_callback=None,
           chi_tim_timeout=False):
        import os
        cac_lan_goi.append((ngay, dung_sau_mis_di))
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, '20260101_ACH_ConfirmMISdi.xlsx')
        open(path, 'wb').write(b'fake-confirm')
        return path
    return _fn


class TestNgayDoiChieuQuaUploadForm:
    """Regression (2026-07-31): route /start có `list[UploadFile]` — tham số kiểu
    đơn giản khác PHẢI khai báo `Form(...)` tường minh, nếu không FastAPI luôn
    dùng giá trị mặc định, im lặng bỏ qua dữ liệu client gửi lên. Phát hiện khi
    thêm `bo_qua_checkpoint`, hoá ra `ngay_doi_chieu` cũng bị lỗi y hệt từ trước
    tới giờ (chưa từng có test nào phủ qua đường upload)."""

    def test_ngay_doi_chieu_toi_dung_pipeline_qua_upload(self, admin_client, monkeypatch, tmp_path):
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan_tham_so(cac_lan_goi))

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': '15/07/2026'},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']
        _wait_status(job_id, 'awaiting_confirmation')
        assert cac_lan_goi == [('15/07/2026', True)]


def _stub_ghi_nhan_dung_sau_mis_di(cac_lan_goi: list):
    """Ghi lại giá trị `dung_sau_mis_di` mỗi lần main_from_dir() được gọi, trả
    kết quả tương ứng (file confirm nếu True, báo cáo cuối nếu False) — dùng để
    khẳng định đúng giá trị được truyền xuống pipeline theo cờ bo_qua_checkpoint."""
    def _fn(input_dir, output_dir, ngay=None, log_callback=None, cancel_event=None,
           dung_sau_mis_di=False, xac_nhan_path=None, summary_callback=None,
           chi_tim_timeout=False):
        import os
        cac_lan_goi.append(dung_sau_mis_di)
        os.makedirs(output_dir, exist_ok=True)
        if dung_sau_mis_di:
            path = os.path.join(output_dir, '20260101_ACH_ConfirmMISdi.xlsx')
            open(path, 'wb').write(b'fake-confirm')
            return path
        path = os.path.join(output_dir, 'doi_chieu_20260101.xlsx')
        open(path, 'wb').write(b'fake-final')
        return path
    return _fn


class TestBoQuaCheckpointUpload:
    def test_mac_dinh_khong_truyen_co_van_dung_o_checkpoint(self, admin_client, monkeypatch, tmp_path):
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan_dung_sau_mis_di(cac_lan_goi))

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        job = _wait_status(job_id, 'awaiting_confirmation')
        assert job['status'] == 'awaiting_confirmation'
        assert cac_lan_goi == [True]

    def test_bat_co_chay_thang_toi_done_ngay_lan_dau(self, admin_client, monkeypatch, tmp_path):
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan_dung_sau_mis_di(cac_lan_goi))

        r = admin_client.post(
            '/api/ach/start',
            files=[('files', ('GW.xlsx', b'fake', _XLSX_MIME))],
            data={'ngay_doi_chieu': '', 'bo_qua_checkpoint': 'true'},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']
        job = _wait_status(job_id, 'done')
        assert job['status'] == 'done'
        assert 'doi_chieu_20260101.xlsx' in job['files']
        assert cac_lan_goi == [False]


class TestBoQuaCheckpointFolder:
    def test_mac_dinh_khong_truyen_co_van_dung_o_checkpoint(self, admin_client, monkeypatch, tmp_path):
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan_dung_sau_mis_di(cac_lan_goi))
        folder = tmp_path / 'server_folder'
        folder.mkdir()

        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(folder), 'ngay_doi_chieu': ''},
        )
        job_id = r.json()['job_id']
        job = _wait_status(job_id, 'awaiting_confirmation')
        assert job['status'] == 'awaiting_confirmation'
        assert cac_lan_goi == [True]

    def test_bat_co_chay_thang_toi_done_ngay_lan_dau(self, admin_client, monkeypatch, tmp_path):
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan_dung_sau_mis_di(cac_lan_goi))
        folder = tmp_path / 'server_folder'
        folder.mkdir()

        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(folder), 'ngay_doi_chieu': '', 'bo_qua_checkpoint': True},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']
        job = _wait_status(job_id, 'done')
        assert job['status'] == 'done'
        assert cac_lan_goi == [False]

    def test_chay_thang_van_copy_ket_qua_ve_thu_muc_nguon(self, admin_client, monkeypatch, tmp_path):
        """Bỏ qua Checkpoint không được phá vỡ tính năng copy kết quả về thư mục
        nguồn (mode folder, Bước 4 UX cũ) — vẫn phải hoạt động như bình thường."""
        cac_lan_goi = []
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_ghi_nhan_dung_sau_mis_di(cac_lan_goi))
        source_folder = tmp_path / 'du_lieu_nguon'
        source_folder.mkdir()

        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(source_folder), 'ngay_doi_chieu': '', 'bo_qua_checkpoint': True},
        )
        job_id = r.json()['job_id']
        job = _wait_status(job_id, 'done')

        dest = source_folder / 'Output' / 'doi_chieu_20260101.xlsx'
        assert dest.exists()
        assert job['final_output_dir'] == str(source_folder / 'Output')
        assert job['copy_error'] is None
