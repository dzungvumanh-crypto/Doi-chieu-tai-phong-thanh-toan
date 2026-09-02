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

import time

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
