"""Test trần dung lượng upload /api/ilo1000/start (review PR#68 mục P68-5, khanhbq693).

Trước fix: `await f.read()` đọc TRỌN file vào RAM rồi mới kiểm dung lượng — file
oversized đã nạp hết trước khi bị từ chối. Nay đọc theo khối 1MB, dừng ngay khi
vượt trần, không giữ nguyên file oversized trong RAM.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ilo1000_upload_limit.py -v
"""

from unittest.mock import patch

import backend.api.ilo1000 as ilo1000_api


class TestUploadLimit:
    def test_tong_dung_luong_vuot_tran_bi_tu_choi_413(self, admin_client, monkeypatch):
        monkeypatch.setattr(ilo1000_api, '_MAX_UPLOAD', 10)  # 10 byte cho dễ test
        with patch.object(ilo1000_api.ilo1000_service, 'start_job') as mock_start:
            r = admin_client.post(
                '/api/ilo1000/start',
                files=[('files', ('a.csv', b'x' * 20, 'text/csv'))],
            )
        assert r.status_code == 413
        mock_start.assert_not_called()

    def test_trong_tran_van_chay_binh_thuong(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(ilo1000_api.ilo1000_service, 'start_job', lambda saved: 'fake-job-id')
        r = admin_client.post(
            '/api/ilo1000/start',
            files=[('files', ('a.csv', b'noi dung nho', 'text/csv'))],
        )
        assert r.status_code == 200
        assert r.json()['job_id'] == 'fake-job-id'

    def test_nhieu_file_cong_don_dung_luong_vuot_tran(self, admin_client, monkeypatch):
        """Trần áp cho TỔNG các file trong 1 lượt, không phải riêng từng file."""
        monkeypatch.setattr(ilo1000_api, '_MAX_UPLOAD', 15)
        with patch.object(ilo1000_api.ilo1000_service, 'start_job') as mock_start:
            r = admin_client.post(
                '/api/ilo1000/start',
                files=[
                    ('files', ('a.csv', b'x' * 10, 'text/csv')),
                    ('files', ('b.csv', b'y' * 10, 'text/csv')),
                ],
            )
        assert r.status_code == 413
        mock_start.assert_not_called()


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
