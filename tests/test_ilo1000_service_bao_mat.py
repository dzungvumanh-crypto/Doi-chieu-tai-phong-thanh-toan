"""Test bảo mật cho backend/services/ilo1000_service.py — chốt chặn hồi quy.

Review PR#68 (khanhbq693): `start_job()` ghi file theo tên client gửi lên
(`UploadFile.filename`) thẳng vào `input_dir`, không qua `os.path.basename()`.
Một tên file cố ý mang `..\\..\\..\\` sẽ ghi ra NGOÀI thư mục tạm của job — kể cả
đè lên mã nguồn hệ thống nếu đường dẫn đủ sâu. Vá bằng os.path.basename()
(cùng cách `doi_chieu_song_phuong_kenh_core_service.py:119` đã dùng).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ilo1000_service_bao_mat.py -v
"""

import time

from backend.services import ilo1000_service as svc


class TestStartJobChanPathTraversal:
    def test_ten_file_mang_duong_dan_bi_cat_ve_basename(self, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        # Không chạy pipeline thật — job_id chỉ cần tồn tại đủ lâu để kiểm tra
        # file đã ghi trước khi thread nền (chạy pipeline thật, sẽ lỗi vì input
        # rác) kịp dọn/đổi trạng thái.
        job_id = svc.start_job({'..\\..\\..\\evil.txt': b'malicious'})

        input_dir = tmp_path / job_id / 'input'
        # File PHẢI nằm trong input_dir, tên bị cắt về basename — không văng ra
        # ngoài theo '..\\..\\..\\'.
        assert (input_dir / 'evil.txt').exists()
        assert (input_dir / 'evil.txt').read_bytes() == b'malicious'
        # Không có file/thư mục nào bị tạo ra ngoài phạm vi TEMP_DIR.
        assert not (tmp_path.parent / 'evil.txt').exists()

        time.sleep(0.05)  # để thread nền (lỗi ngay vì input rác) không văng ra ngoài test
