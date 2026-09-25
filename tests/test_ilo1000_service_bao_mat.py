"""Test bảo mật cho endpoint `POST /api/ilo1000/start` — chốt chặn hồi quy.

Review PR#68 (khanhbq693): route ghi file theo tên client gửi lên
(`UploadFile.filename`) thẳng vào `input_dir`, không qua `safe_filename()`.
Một tên file cố ý mang `../../` sẽ ghi ra NGOÀI thư mục tạm của job — kể cả
đè lên mã nguồn hệ thống nếu đường dẫn đủ sâu.

2026-09-02 (review khanhbq693 PR#70 mục A/B): việc sanitize tên file (từng là
`ilo1000_service.start_job()`, nhận thẳng `dict[str, bytes]`) đã chuyển hẳn lên
lớp API (`backend/api/ilo1000.py::start_job`, dùng `safe_filename()` +
`save_upload_to()` — bỏ chế độ "chọn thư mục máy chủ", chỉ còn tải file lên).
Test này đổi từ gọi thẳng service sang gọi qua HTTP, đúng khuôn mẫu
`test_doi_chieu_song_phuong_kenh_core_api.py::test_ten_file_co_duong_dan_bi_cat_ve_ten_thuan`.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ilo1000_service_bao_mat.py -v
"""

import sqlite3
import time

import pytest

from backend.services import ilo1000_service as svc


class TestStartJobChanPathTraversal:
    def test_ten_file_co_duong_dan_bi_cat_ve_ten_thuan(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)

        r = admin_client.post(
            '/api/ilo1000/start',
            files=[('files', ('../../evil.txt', b'malicious', 'text/plain'))],
        )
        assert r.status_code == 200
        job_id = r.json()['job_id']

        input_dir = tmp_path / job_id / 'input'
        # File PHẢI nằm trong input_dir, tên bị cắt về phần tên thuần — không văng ra
        # ngoài theo '../../'.
        assert (input_dir / 'evil.txt').exists()
        assert (input_dir / 'evil.txt').read_bytes() == b'malicious'
        # Không có file/thư mục nào bị tạo ra ngoài phạm vi TEMP_DIR.
        assert not (tmp_path.parent / 'evil.txt').exists()

        # Không chạy pipeline thật — input rác nên thread nền sẽ lỗi ngay; chờ chút để
        # nó không văng exception ra ngoài phạm vi test.
        time.sleep(0.05)


class TestChayJobQuaDuongThat:
    """
    `_run()` mở kết nối DB thật (`sqlite3.connect(DB_PATH, ...)`) để truyền vào
    `main_from_dir(db=...)` tra lịch nghỉ lễ — TRƯỚC ĐÂY dùng nhầm
    `db = get_db()` (generator function của FastAPI `Depends()`, gọi trần trụi
    không phải `sqlite3.Connection`) khiến MỌI job thật crash ngay dòng
    `tai_lich()` gọi `db.execute(...)`. Không phát hiện được bằng test cũ vì
    `TestMainFromDirLichNghiLeDai` gọi thẳng `main_from_dir(db=...)`, bỏ qua
    hẳn lớp `_run()`/`chay_job()`. Test này đi đúng đường production
    (`tao_job()` → ghi file → `chay_job()` → poll `get_job()`), phát hiện
    2026-09-08 qua phản biện độc lập trước PR.
    """

    @pytest.fixture
    def db_path_that(self, tmp_path, monkeypatch):
        """`DB_PATH` module-level trong `ilo1000_service` — monkeypatch để
        `_run()` mở đúng file tạm này (không đụng DB thật)."""
        p = tmp_path / 'ilo1000_test.db'
        conn = sqlite3.connect(p)
        conn.executescript("""
            CREATE TABLE public_holidays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL UNIQUE,
                name TEXT NOT NULL);
            CREATE TABLE duty_special_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE NOT NULL,
                day_type VARCHAR(20) NOT NULL,
                label VARCHAR(100),
                is_confirmed BOOLEAN DEFAULT 0,
                created_at DATETIME);
        """)
        conn.commit()
        conn.close()
        monkeypatch.setattr(svc, 'DB_PATH', str(p))
        return p

    def _write_citad(self, path, trx_date):
        path.write_text(
            'SERIAL_NO,RELATION_NO,TRX_DATE,AMOUNT,TRX_STATUS,extra\n'
            f'1,2003OTT26090100001,{trx_date},100000,OK,\n',
            encoding='utf-8',
        )

    def _write_core(self, path, trdate):
        path.write_text(
            'TRDATE,TRBRCD,USERID,JOURSEQ,DYTRSEQ,LOCAC,CCY,BUSCD,UNIT,TRCD,CUSTOMER,TRTP,REFERENCE,REMARK,DRAMOUNT,CRAMOUNT,CRTDTM\n'
            f'{trdate},2003,2003OSB,1,1,501202,VND,GL,IB,  ,1000-000007709,Normal,'
            f'2003OTT26090100001,test,0,100000,{trdate} 09:00:00\n',
            encoding='utf-8',
        )

    def test_job_chay_that_khong_crash_vi_db_sai_kieu(self, tmp_path, db_path_that):
        """Trước fix: status='error', job['error'] = "'generator' object has no
        attribute 'execute'". Sau fix: chạy xong bình thường, có file kết quả."""
        job_id, input_dir = svc.tao_job()
        try:
            self._write_core(input_dir / '1000_gl02_20260706.csv', '20260706')
            self._write_citad(input_dir / 'citad_pool.csv', '20260706')

            svc.chay_job(job_id)

            job = svc.get_job(job_id)
            for _ in range(100):  # tối đa 5s, job này rất nhỏ nên thường xong ngay
                if job['status'] in ('done', 'error', 'cancelled'):
                    break
                time.sleep(0.05)

            assert job['error'] is None, f"Job lỗi: {job['error']}"
            assert job['status'] == 'done', f"status={job['status']!r}, logs={job['logs']}"
            assert len(job['files']) >= 1
        finally:
            svc.bo_job(job_id)
