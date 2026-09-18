"""Mọi cửa đối chiếu nặng chạy pipeline ở TIẾN TRÌNH RIÊNG (card 150 Implementation-notes).

Hai lớp canh:
  1. Tĩnh — service nào khai `dang_ky_nguon()` (tức là cửa đối chiếu nặng) mà không gọi
     `chay_tach()` thì đỏ. Module đối chiếu mới chép khuôn cũ là chạy lại trong luồng web,
     tranh GIL với mọi request mà không ai biết.
  2. Chạy thật từng module qua tiến trình con với đầu vào hỏng/rỗng — không cần dữ liệu
     ngân hàng mà vẫn đi qua đủ đường ống: log, tiến độ, lỗi mang về đúng kiểu.

Test ở đây KHÔNG được vá biến toàn cục của module (TEMP_DIR...): tiến trình con không
thấy bản vá, sẽ ghi vào `data/temp_*` thật. Chỉ truyền đường dẫn tường minh.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_doi_chieu_chay_tien_trinh_rieng.py -v
"""
import logging
import re
from pathlib import Path

import pytest

_GOC = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _bat_tien_trinh(tien_trinh_that):
    pass  # conftest mặc định chạy trong luồng


def _thay_tach(caplog) -> bool:
    return any("tiến trình riêng" in r.getMessage() for r in caplog.records)


# ── 1. Lưới canh tĩnh ──

def test_moi_cua_doi_chieu_deu_chay_tach():
    thieu = []
    for f in sorted((_GOC / "backend" / "services").rglob("*.py")):
        ma = f.read_text(encoding="utf-8")
        if re.search(r"^dang_ky_nguon\(", ma, re.M) and "chay_tach(" not in ma:
            thieu.append(str(f.relative_to(_GOC)))
    assert not thieu, (
        f"Cửa đối chiếu nặng chưa chạy tách tiến trình: {thieu}. Gọi pipeline qua "
        f"backend/core/tien_trinh_doi_chieu.py::chay_tach() — xem DESIGN.md."
    )


# ── 2. Chạy thật từng module ──

def test_ach(tmp_path, caplog):
    from backend.services import ach_service as svc
    job_id, input_dir = svc.tao_job()
    job = svc.get_job(job_id)
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc._run(job_id, str(input_dir), job["output_dir"], "15/07/2026")
        assert job["status"] == "error"
        assert "file PDF" in job["error"]                   # FileNotFoundError từ con
        assert "Ngày đối chiếu: 15/07/2026" in job["logs"]  # log của pipeline về tới job
        assert _thay_tach(caplog)
    finally:
        svc.bo_job(job_id)


@pytest.mark.parametrize("ten_mod", [
    "doi_chieu_song_phuong_kenh_core_service",
    "doi_chieu_song_phuong_kenh_core_di_service",
])
def test_song_phuong_den_di(ten_mod, caplog):
    import importlib
    svc = importlib.import_module(f"backend.services.{ten_mod}")
    job_id, input_dir = svc.tao_job("20260715", "201")
    job = svc.get_job(job_id)
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc._run(job_id, str(input_dir), job["ngay"], job["ma_nh"], job["output_dir"])
        assert job["status"] == "error", job["error"]
        assert job["stage"] == 2                    # stage_callback từ con về tới job
        trang_thai = job["ket_qua"]["trang_thai"]   # ket_qua điền trong con, ghi lại ở cha
        assert all(v and v["trang_thai"] == "chua_doi_chieu" for v in trang_thai.values()), trang_thai
        assert _thay_tach(caplog)
    finally:
        svc.bo_job(job_id)


def test_cham459901(tmp_path, caplog):
    from backend.services import cham459901_service as svc
    hong = tmp_path / "GL02_hong.zip"
    hong.write_bytes(b"khong phai zip")
    token = svc.init_progress()
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc.run_process([("GL02_hong.zip", hong)], token)
        p = svc.get_progress(token)
        assert p["done"] and p["error"] and not p["cancelled"]
        # InputError mang về đúng kiểu → thông báo thẳng cho người dùng, không phải
        # "Lỗi xử lý — xem log server" của nhánh lỗi hệ thống
        assert p["msg"] == p["error"]
        assert p["pct"] >= 5                        # tiến độ từ con về tới _progress của cha
        assert _thay_tach(caplog)
    finally:
        svc.bo_luot(token)


def test_song_phuong_phan_loai(tmp_path, caplog):
    from backend.services import doi_chieu_song_phuong_service as svc
    hong = tmp_path / "du_lieu.zip"
    hong.write_bytes(b"PK" + b"than hong")   # qua cửa magic bytes → tới bước báo tiến độ
    token = svc.init_progress()
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc.run_process(hong, token)
        p = svc.get_progress(token)
        assert p["done"] and p["error"]
        assert p["pct"] >= 5                        # tiến độ từ con về tới _progress của cha
        assert _thay_tach(caplog)
    finally:
        svc.bo_luot(token)


def test_osb(tmp_path, caplog):
    from backend.services import doi_chieu_osb_job as svc
    gl02 = tmp_path / "GL02.zip"
    gl02.write_bytes(b"khong phai zip")
    osb = tmp_path / "OSB.xlsx"
    osb.write_bytes(b"khong phai xlsx")
    token = svc.init_progress()
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc.run_process(gl02, [osb], "459902", "20260715", token)
        p = svc.get_progress(token)
        assert p["done"] and p["error"]
        assert p["pct"] >= 10                       # tiến độ từ con về tới _progress của cha
        assert _thay_tach(caplog)
    finally:
        svc.bo_luot(token)
