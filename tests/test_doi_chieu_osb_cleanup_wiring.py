"""Regression test — review Khánh trên PR #103: module `doi_chieu_osb` không có
`_cleanup_old_results()` và không nằm trong sổ đăng ký của `temp_cleanup_service.py::
run_cleanup()`, nên lịch dọn 23h không bao giờ dọn được `data/temp_doi_chieu_osb/` (rác
`upload_<token>/` + thư mục kết quả tích luỹ vĩnh viễn).

Test này khoá lại: gọi `run_cleanup()` thật (không mock) và xác nhận thư mục quá hạn của
`doi_chieu_osb` THỰC SỰ bị xoá, không chỉ "không raise lỗi" — mirror
`test_cham459901_cleanup_wiring.py`.
"""

import os
import time

from backend.services import doi_chieu_osb_job as job
from backend.services import temp_cleanup_service


def test_run_cleanup_actually_removes_stale_doi_chieu_osb_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "TEMP_DIR", tmp_path)
    job._progress.clear()

    stale_result_dir = tmp_path / "some-old-result-token"
    stale_result_dir.mkdir()
    stale_upload_dir = tmp_path / "upload_some-old-task-token"
    stale_upload_dir.mkdir()
    old_mtime = time.time() - 999_999
    os.utime(stale_result_dir, (old_mtime, old_mtime))
    os.utime(stale_upload_dir, (old_mtime, old_mtime))

    # cutoff SAU thời điểm tạo thư mục -> phải bị coi là quá hạn và xoá.
    temp_cleanup_service.run_cleanup(cutoff=time.time())

    assert not stale_result_dir.exists(), (
        "doi_chieu_osb_job._cleanup_old_results() không chạy được từ run_cleanup() — có thể "
        "chưa đăng ký, hoặc chữ ký hàm lệch (TypeError bị nuốt, chỉ log ERROR)."
    )
    assert not stale_upload_dir.exists(), (
        "Thư mục upload_<token> (file GL02/OSB gốc) phải bị dọn cùng cơ chế với thư mục kết quả."
    )


def test_run_process_deletes_upload_dir_even_on_success(tmp_path, monkeypatch):
    """`run_process()` phải xoá `upload_<token>/` ở CUỐI, kể cả nhánh chạy xong bình thường —
    trước đây chỉ nhánh upload hỏng mới được `bo_luot()` dọn."""
    monkeypatch.setattr(job, "TEMP_DIR", tmp_path)
    job._progress.clear()

    task_token = "test-task-token"
    upload_dir = tmp_path / f"upload_{task_token}"
    upload_dir.mkdir()
    gl02_path = upload_dir / "gl02.zip"
    gl02_path.write_bytes(b"")
    osb_path = upload_dir / "osb.xlsx"
    osb_path.write_bytes(b"")

    job._progress[task_token] = {
        "pct": 0, "msg": "", "done": False, "error": None, "cancelled": False,
        "result": None, "_ts": time.time(),
    }
    monkeypatch.setattr(
        job, "process",
        lambda gl02_path, osb_paths, ma_tk, ngay, task_token=None: {"token": "r1"},
    )

    job.run_process(gl02_path, [osb_path], "519910", "20260701", task_token)

    assert not upload_dir.exists(), (
        "run_process() thành công vẫn phải xoá upload_<token>/ — trước fix, thư mục này chỉ bị "
        "xoá ở nhánh upload lỗi (bo_luot()), lượt chạy thành công để lại rác vĩnh viễn."
    )
    assert job._progress[task_token]["done"] is True


def test_run_process_khong_xoa_thu_muc_chua_file_nam_ngoai_upload(tmp_path, monkeypatch):
    """Thư mục xoá phải dựng từ `task_token`, không suy ra từ `gl02_path.parent`. File nằm ở thư
    mục dữ liệu thật trên máy chủ (kiểu chế độ chọn thư mục của Chấm 459901) thì thư mục đó
    phải còn nguyên — `rmtree(gl02_path.parent)` sẽ xoá sạch nó."""
    temp_dir = tmp_path / "temp"
    monkeypatch.setattr(job, "TEMP_DIR", temp_dir)
    job._progress.clear()

    thu_muc_that = tmp_path / "du_lieu_that"
    thu_muc_that.mkdir()
    gl02_path = thu_muc_that / "gl02.zip"
    gl02_path.write_bytes(b"")
    osb_path = thu_muc_that / "osb.xlsx"
    osb_path.write_bytes(b"")

    task_token = "tok-ngoai"
    upload_dir = job.tao_thu_muc_upload(task_token)
    job._progress[task_token] = {
        "pct": 0, "msg": "", "done": False, "error": None, "cancelled": False,
        "result": None, "_ts": time.time(),
    }
    monkeypatch.setattr(
        job, "process",
        lambda gl02_path, osb_paths, ma_tk, ngay, task_token=None: {"token": "r1"},
    )

    job.run_process(gl02_path, [osb_path], "519910", "20260701", task_token)

    assert gl02_path.exists() and osb_path.exists(), "Xoá nhầm thư mục dữ liệu nằm ngoài upload_<token>/"
    assert not upload_dir.exists()
