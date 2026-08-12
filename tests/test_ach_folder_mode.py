"""Test tính năng "chọn thư mục server" (mode folder) của module ACH — chưa có test
nào trước đây (Milestone C: review tính năng đã có sẵn từ trước khi chốt Rule mới).

- validate_required_files(): thuật toán thuần (kiểm tra tên file), test trực tiếp.
- /api/ach/validate_folder, /api/ach/start_folder: API-level qua admin_client,
  monkeypatch main_from_dir (như test_ach_checkpoint_api.py) để không chạy pipeline
  thật — chỉ kiểm tra hợp đồng request/response + job có chạy đúng chế độ Checkpoint
  (dung_sau_khop_gw=True, nhất quán với mode upload).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_folder_mode.py -v
"""

from backend.services import ach_service as svc
from backend.services.ach.validate import validate_required_files
from tests.test_ach_checkpoint_api import _stub_main_from_dir, _wait_status

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_FULL_SET = [
    'ACH_20260707_VBAAVNVN_NRT_16302_N03_1.pdf',
    'GL02_20260707_1000.zip',
    'di GW 07.07.xlsx',
    'doichieugd_20260706__01_DI_9999_N.zip',
    'doichieugd_20260707__01_DI_9999_N.zip',
    'doichieugd_20260706__01_DEN_9999_N.zip',
    'doichieugd_20260707__01_DEN_9999_N.zip',
]


class TestValidateRequiredFiles:
    def test_bo_file_du_ok_true(self):
        res = validate_required_files(_FULL_SET)
        assert res['ok'] is True
        assert all(c['ok'] for c in res['checks'])

    def test_thieu_pdf_bao_loi_rieng_pdf(self):
        res = validate_required_files([f for f in _FULL_SET if not f.endswith('.pdf')])
        assert res['ok'] is False
        pdf_check = next(c for c in res['checks'] if 'PDF' in c['label'])
        assert pdf_check['ok'] is False

    def test_pdf_ten_sai_dinh_dang_khong_nrt_van_bi_bao_thieu(self):
        names = [f for f in _FULL_SET if not f.endswith('.pdf')] + ['random_report.pdf']
        res = validate_required_files(names)
        pdf_check = next(c for c in res['checks'] if 'PDF' in c['label'])
        assert pdf_check['ok'] is False

    def test_thieu_gl02_bao_loi(self):
        res = validate_required_files([f for f in _FULL_SET if not f.startswith('GL02')])
        gl02_check = next(c for c in res['checks'] if 'GL02' in c['label'])
        assert gl02_check['ok'] is False
        assert res['ok'] is False

    def test_thieu_gw_xlsx_bao_loi(self):
        res = validate_required_files([f for f in _FULL_SET if 'GW' not in f])
        gw_check = next(c for c in res['checks'] if 'GW' in c['label'])
        assert gw_check['ok'] is False

    def test_xlsx_khong_co_chu_gw_van_ok_nhung_ghi_chu_do_nghi(self):
        names = [f.replace('di GW 07.07.xlsx', 'khac.xlsx') for f in _FULL_SET]
        res = validate_required_files(names)
        gw_check = next(c for c in res['checks'] if 'GW' in c['label'])
        assert gw_check['ok'] is True
        assert 'dò nội dung' in gw_check['detail']

    def test_chi_1_file_di_bao_thieu_can_2(self):
        names = [f for f in _FULL_SET if '_DI_' not in f] + ['doichieugd_20260707__01_DI_9999_N.zip']
        res = validate_required_files(names)
        di_check = next(c for c in res['checks'] if 'MIS_DI' in c['label'])
        assert di_check['ok'] is False

    def test_chi_1_file_den_bao_thieu_can_2(self):
        names = [f for f in _FULL_SET if '_DEN_' not in f] + ['doichieugd_20260707__01_DEN_9999_N.zip']
        res = validate_required_files(names)
        den_check = next(c for c in res['checks'] if 'MIS_DEN' in c['label'])
        assert den_check['ok'] is False


class TestValidateFolderApi:
    def test_folder_khong_ton_tai_bao_loi_400(self, admin_client, tmp_path):
        r = admin_client.post(
            '/api/ach/validate_folder',
            json={'folder_path': str(tmp_path / 'khong_ton_tai'), 'ngay_doi_chieu': ''},
        )
        assert r.status_code == 400

    def test_folder_ton_tai_rong_bao_thieu_het(self, admin_client, tmp_path):
        folder = tmp_path / 'empty_folder'
        folder.mkdir()
        r = admin_client.post(
            '/api/ach/validate_folder',
            json={'folder_path': str(folder), 'ngay_doi_chieu': ''},
        )
        assert r.status_code == 200
        assert r.json()['ok'] is False

    def test_folder_du_file_ok_true(self, admin_client, tmp_path):
        folder = tmp_path / 'du_file'
        folder.mkdir()
        for name in _FULL_SET:
            (folder / name).write_bytes(b'x')
        r = admin_client.post(
            '/api/ach/validate_folder',
            json={'folder_path': str(folder), 'ngay_doi_chieu': ''},
        )
        assert r.status_code == 200
        assert r.json()['ok'] is True


class TestStartFolderApi:
    def test_folder_khong_ton_tai_bao_loi_400(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(tmp_path / 'khong_ton_tai'), 'ngay_doi_chieu': ''},
        )
        assert r.status_code == 400

    def test_folder_hop_le_tao_job_va_cung_dung_o_checkpoint(
        self, admin_client, monkeypatch, tmp_path,
    ):
        """Mode folder phải nhất quán với mode upload: cũng luôn chạy Checkpoint
        (dung_sau_khop_gw=True), không có đường tắt bỏ qua xác nhận thủ công."""
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(svc, 'main_from_dir', _stub_main_from_dir())
        folder = tmp_path / 'server_folder'
        folder.mkdir()

        r = admin_client.post(
            '/api/ach/start_folder',
            json={'folder_path': str(folder), 'ngay_doi_chieu': '07/07/2026'},
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']

        job = _wait_status(job_id, 'awaiting_confirmation')
        assert job['status'] == 'awaiting_confirmation'
        assert job['input_dir'] == str(folder)
        assert job['ngay'] == '07/07/2026'
