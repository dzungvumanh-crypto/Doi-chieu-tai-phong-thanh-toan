"""Test trần dung lượng upload /api/ilo1000/start (review PR#68 mục P68-5, khanhbq693).

Trước fix: `await f.read()` đọc TRỌN file vào RAM rồi mới kiểm dung lượng — file
oversized đã nạp hết trước khi bị từ chối. Nay đọc theo khối 1MB, dừng ngay khi
vượt trần, không giữ nguyên file oversized trong RAM.

2026-09-02 (review khanhbq693 PR#70 mục A/B): `ilo1000_service.start_job(saved_files)`
bị bỏ, thay bằng bộ ba `tao_job()` / `bo_job()` / `chay_job()` — route ghi thẳng từng
khối file xuống đĩa (`save_upload_to()`) thay vì gom hết vào RAM trước khi gọi service.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ilo1000_upload_limit.py -v
"""

from unittest.mock import MagicMock

import backend.api.ilo1000 as ilo1000_api
from backend.core.uploads import MAX_REQUEST_BYTES


def test_tran_ilo1000_nho_hon_tran_than_request():
    """Nếu trần ILO1000 >= trần thân request (MAX_REQUEST_BYTES, mặc định 600MB) thì
    BodySizeLimitMiddleware chặn TRƯỚC — client chỉ thấy socket đứt kiểu "[WinError 10054]",
    không đọc được thông báo 413 rõ ràng của route (cùng bài học đã dính ở ACH, xem
    tests/test_ach_tran_upload.py)."""
    assert ilo1000_api._MAX_UPLOAD < MAX_REQUEST_BYTES


class TestUploadLimit:
    def test_tong_dung_luong_vuot_tran_bi_tu_choi_413(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(ilo1000_api, '_MAX_UPLOAD', 10)  # 10 byte cho dễ test
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'tao_job', lambda: ('fake-job-id', tmp_path))
        mock_bo = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'bo_job', mock_bo)
        mock_chay = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'chay_job', mock_chay)

        r = admin_client.post(
            '/api/ilo1000/start',
            files=[('files', ('a.csv', b'x' * 20, 'text/csv'))],
        )
        assert r.status_code == 413
        mock_chay.assert_not_called()
        # Job vượt trần phải được dọn ngay, không để lại 1 job 'pending' mồ côi.
        mock_bo.assert_called_once_with('fake-job-id')

    def test_trong_tran_van_chay_binh_thuong(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'TEMP_DIR', tmp_path)
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'tao_job', lambda: ('fake-job-id', tmp_path))
        mock_bo = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'bo_job', mock_bo)
        mock_chay = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'chay_job', mock_chay)

        r = admin_client.post(
            '/api/ilo1000/start',
            files=[('files', ('a.csv', b'noi dung nho', 'text/csv'))],
        )
        assert r.status_code == 200
        assert r.json()['job_id'] == 'fake-job-id'
        mock_chay.assert_called_once_with('fake-job-id')
        mock_bo.assert_not_called()

    def test_nhieu_file_cong_don_dung_luong_vuot_tran(self, admin_client, monkeypatch, tmp_path):
        """Trần áp cho TỔNG các file trong 1 lượt, không phải riêng từng file."""
        monkeypatch.setattr(ilo1000_api, '_MAX_UPLOAD', 15)
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'tao_job', lambda: ('fake-job-id', tmp_path))
        mock_bo = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'bo_job', mock_bo)
        mock_chay = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'chay_job', mock_chay)

        r = admin_client.post(
            '/api/ilo1000/start',
            files=[
                ('files', ('a.csv', b'x' * 10, 'text/csv')),
                ('files', ('b.csv', b'y' * 10, 'text/csv')),
            ],
        )
        assert r.status_code == 413
        mock_chay.assert_not_called()
        mock_bo.assert_called_once_with('fake-job-id')

    def test_hai_file_cung_ten_bi_tu_choi_400(self, admin_client, monkeypatch, tmp_path):
        """2 file cùng tên trong 1 lượt upload phải bị chặn ngay — file sau sẽ ghi đè file
        trước trong input_dir mà không ai hay biết nếu không chặn."""
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'tao_job', lambda: ('fake-job-id', tmp_path))
        mock_bo = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'bo_job', mock_bo)
        mock_chay = MagicMock()
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'chay_job', mock_chay)

        r = admin_client.post(
            '/api/ilo1000/start',
            files=[
                ('files', ('a.csv', b'noi dung 1', 'text/csv')),
                ('files', ('a.csv', b'noi dung 2', 'text/csv')),
            ],
        )
        assert r.status_code == 400
        assert 'cùng tên' in r.json()['detail']
        mock_chay.assert_not_called()
        mock_bo.assert_called_once_with('fake-job-id')


class _FakeUpload:
    filename = "fake.bin"

    def __init__(self, data: bytes):
        self._buf = data
        self._pos = 0

    async def read(self, n):
        chunk = self._buf[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


def _doc(data: bytes, max_bytes: int) -> bytes:
    import asyncio

    from backend.core.uploads import read_limited
    return asyncio.run(read_limited(_FakeUpload(data), max_bytes))


class TestReadLimited:
    def test_doc_dung_du_lieu_trong_tran(self):
        assert _doc(b'hello world', max_bytes=100) == b'hello world'

    def test_vuot_tran_raise_413(self):
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _doc(b'x' * 100, max_bytes=10)
        assert exc_info.value.status_code == 413

    def test_dung_luong_dung_bang_tran_khong_bi_tu_choi(self):
        assert _doc(b'x' * 10, max_bytes=10) == b'x' * 10
