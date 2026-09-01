"""Regression test — PR#63 đổi chữ ký `_cleanup_old_results()` (bỏ tham số `cutoff`)
mà `temp_cleanup_service.py:run_cleanup()` vẫn gọi `ham(cutoff)` (1 tham số). Hậu quả:
TypeError bị nuốt bởi `except Exception` trong `run_cleanup()`, chỉ log ERROR — lịch dọn
23h không bao giờ dọn được thư mục Chấm 459901 (xem Implementation-notes.html).

Test này khoá lại: gọi `run_cleanup()` thật (không mock) và xác nhận thư mục kết quả
459901 quá hạn THỰC SỰ bị xoá, không chỉ "không raise lỗi".
"""

import time

from backend.services import cham459901_service as svc
from backend.services import temp_cleanup_service


def test_run_cleanup_actually_removes_stale_cham459901_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
    svc._progress.clear()

    stale_dir = tmp_path / "some-old-result-token"
    stale_dir.mkdir()
    old_mtime = time.time() - 999_999
    import os
    os.utime(stale_dir, (old_mtime, old_mtime))

    # cutoff SAU thời điểm tạo thư mục -> phải bị coi là quá hạn và xoá.
    temp_cleanup_service.run_cleanup(cutoff=time.time())

    assert not stale_dir.exists(), (
        "_cleanup_old_results(cutoff) không chạy được — có thể chữ ký hàm và cách gọi "
        "ở temp_cleanup_service.py lại lệch nhau (TypeError bị nuốt, chỉ log ERROR)."
    )
